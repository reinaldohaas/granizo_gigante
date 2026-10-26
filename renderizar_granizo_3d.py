"""
Visualizacao 3D da supercelula de granizo (WRF d03, 2026-08-29) no ParaView.

Camadas:
  - Relevo em tons terrosos dessaturados (nao compete com a tempestade)
  - Trilha de granizo na superficie: HAILCAST_DIAM_MAX acumulado (mm), YlOrRd
  - Nuvem (QCLOUD+QICE+QSNOW >= 0.1 g/kg): branco translucido
  - Chuva (QRAIN >= 1 g/kg): azul
  - Nucleo de graupel/granizo (QGRAUP >= 5 g/kg): magenta opaco

Uso (pvpython):
  renderizar_granizo_3d.py still   -> PNGs do pico (19:30Z) em 3 vistas + estado .pvsm
  renderizar_granizo_3d.py anim    -> frames 16-23Z, MP4 e GIF
"""
import os
import sys
import json
import math
import shutil
import subprocess
from PIL import Image, ImageDraw, ImageFont
from paraview.simple import *

BASE = r'C:\gis4wrf\projects\Floripa\viz_granizo_v2'
DADOS = os.path.join(BASE, 'dados')
SAIDA = os.path.join(BASE, 'saida')
FRAMES = os.path.join(SAIDA, 'frames')
os.makedirs(FRAMES, exist_ok=True)

W, H = 1920, 1080
SCALE = [1.0, 1.0, 1.0]      # exagero vertical ja aplicado nos dados (ver preparar_dados_granizo.py)

# limiares
TH_NUVEM, TH_CHUVA, TH_GRAUPEL, TH_GRANIZO, TH_TRILHA = 0.05, 1.0, 2.0, 7.0, 5.0

# paleta (sRGB 0-1)
def hx(s):
    s = s.lstrip('#')
    return [int(s[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]

COR_NUVEM = hx('#f4f6fa')
COR_CHUVA = hx('#2f7fe0')
COR_GRAUPEL = hx('#f6c2ee')
COR_GRANIZO = hx('#c4129f')
TRILHA = [(5, '#fff3b0'), (15, '#fdc94a'), (25, '#f98a28'), (35, '#e0412b'), (50, '#8f1028')]

meta = json.load(open(os.path.join(DADOS, 'meta.json'), encoding='utf-8'))
FLN = meta['florianopolis_km']           # z ja na escala da cena
VE_T, VE_A = meta['VE_T'], meta['VE_A']

FONT = r'C:\Windows\Fonts\arial.ttf'
FONT_B = r'C:\Windows\Fonts\arialbd.ttf'


# ============================================================== cena
def montar_cena():
    view = CreateView('RenderView')
    view.ViewSize = [W, H]
    view.OrientationAxesVisibility = 0
    view.UseColorPaletteForBackground = 0
    view.BackgroundColorMode = 'Gradient'
    view.Background2 = hx('#0b1220')      # topo
    view.Background = hx('#2a3446')       # base
    view.UseFXAA = 1
    view.EnableRenderOnInteraction = 0
    try:
        view.UseToneMapping = 0
    except AttributeError:
        pass
    # luz-chave vinda de NO, elevada (sombreamento cartografico classico)
    view.KeyLightWarmth = 0.55
    view.KeyLightIntensity = 0.85
    view.KeyLightElevation = 50
    view.KeyLightAzimuth = -30
    view.FillLightKFRatio = 3.5
    view.MaintainLuminance = 1

    relevo = XMLStructuredGridReader(registrationName='Relevo',
                                     FileName=os.path.join(DADOS, 'relevo.vts.series'))
    tempestade = XMLImageDataReader(registrationName='Tempestade_WRF_d03',
                                    FileName=os.path.join(DADOS, 'tempestade.vti.series'))

    # --- relevo
    rd = Show(relevo, view)
    rd.Representation = 'Surface'
    ColorBy(rd, ('POINTS', 'Elevacao_m'))
    lut = GetColorTransferFunction('Elevacao_m')
    lut.ColorSpace = 'Lab'
    lut.RGBPoints = [
        -100.0, *hx('#1a2c40'),
        -1.0, *hx('#1f3550'),
        0.5, *hx('#56634a'),
        150.0, *hx('#66704f'),
        500.0, *hx('#80805c'),
        900.0, *hx('#978a6c'),
        1300.0, *hx('#aa9c84'),
        1700.0, *hx('#cfc8ba'),
    ]
    lut.AutomaticRescaleRangeMode = 'Never'
    rd.SetScalarBarVisibility(view, False)
    rd.Scale = SCALE
    rd.Ambient, rd.Diffuse, rd.Specular = 0.18, 0.9, 0.0
    rd.Interpolation = 'Gouraud'

    # --- trilha de granizo na superficie
    # Clip por escalar (bordas interpoladas, sem o aspecto de pixels do Threshold)
    trilha = Clip(registrationName='Trilha_Granizo_HAILCAST', Input=relevo)
    trilha.ClipType = 'Scalar'
    trilha.Scalars = ['POINTS', 'Granizo_diam_max_mm']
    trilha.Value = TH_TRILHA
    trilha.Invert = 0
    td = Show(trilha, view)
    ColorBy(td, ('POINTS', 'Granizo_diam_max_mm'))
    tl = GetColorTransferFunction('Granizo_diam_max_mm')
    tl.ColorSpace = 'Lab'
    pts = []
    for v, c in TRILHA:
        pts += [float(v), *hx(c)]
    tl.RGBPoints = pts
    tl.AutomaticRescaleRangeMode = 'Never'
    td.SetScalarBarVisibility(view, False)
    td.Scale = SCALE
    td.Translation = [0.0, 0.0, 0.05]
    td.Ambient, td.Diffuse, td.Specular = 0.35, 0.75, 0.0
    td.Opacity = 0.92

    # --- limites
    for fn, nome, cor, larg, op in [('municipios.vtp', 'Municipios', '#e6e9ee', 1.0, 0.30),
                                     ('costa.vtp', 'Costa', '#f2f4f7', 1.8, 0.85),
                                     ('estados.vtp', 'Estados', '#f2f4f7', 2.2, 0.85)]:
        r = XMLPolyDataReader(registrationName=nome, FileName=[os.path.join(DADOS, fn)])
        d = Show(r, view)
        d.ColorArrayName = ['POINTS', '']
        d.AmbientColor = d.DiffuseColor = hx(cor)
        d.LineWidth = larg
        d.Opacity = op
        d.Scale = SCALE
        d.Ambient, d.Diffuse = 1.0, 0.0

    # --- Florianopolis: marcador + rotulo
    pin = Sphere(registrationName='Florianopolis', Center=[FLN[0], FLN[1], FLN[2] + 0.4],
                 Radius=0.9, ThetaResolution=24, PhiResolution=24)
    pd = Show(pin, view)
    pd.AmbientColor = pd.DiffuseColor = [1, 1, 1]
    # (o rotulo e desenhado na sobreposicao 2D, sempre legivel)

    # --- tempestade
    def iso(nome, campo, valor, cor, opac, spec=0.0):
        c = Contour(registrationName=nome, Input=tempestade)
        c.ContourBy = ['POINTS', campo]
        c.Isosurfaces = [valor]
        c.ComputeScalars = 0
        c.ComputeNormals = 1
        s = Show(c, view)
        s.ColorArrayName = ['POINTS', '']
        s.AmbientColor = s.DiffuseColor = cor
        s.Opacity = opac
        s.Scale = SCALE
        s.Specular, s.SpecularPower = spec, 30.0
        s.Interpolation = 'Gouraud'
        return c, s

    # nuvem: renderizacao volumetrica (aspecto de nuvem, sem cascas cinzas sobrepostas)
    vd = Show(tempestade, view)
    vd.Representation = 'Volume'
    ColorBy(vd, ('POINTS', 'QNUVEM_g_kg'))
    vd.SetScalarBarVisibility(view, False)
    vl = GetColorTransferFunction('QNUVEM_g_kg')
    vl.RGBPoints = [0.0, *hx('#9aa6b8'), 0.3, *hx('#dde3ec'), 2.0, *hx('#ffffff')]
    vl.AutomaticRescaleRangeMode = 'Never'
    vo = GetOpacityTransferFunction('QNUVEM_g_kg')
    vo.Points = [0.0, 0.0, 0.5, 0.0,
                 TH_NUVEM, 0.0, 0.5, 0.0,
                 0.3, 0.10, 0.5, 0.0,
                 1.0, 0.30, 0.5, 0.0,
                 3.0, 0.45, 0.5, 0.0]
    vd.ScalarOpacityUnitDistance = 2.2
    vd.Scale = SCALE
    vd.Shade = 1
    vd.Ambient, vd.Diffuse, vd.Specular = 0.55, 0.55, 0.0

    _, cd = iso('Chuva_QRAIN', 'QRAIN_g_kg', TH_CHUVA, COR_CHUVA, 0.55, spec=0.15)
    cd.Ambient, cd.Diffuse = 0.15, 0.85
    _, ge = iso('Graupel_QGRAUP_envoltorio', 'QGRAUP_g_kg', TH_GRAUPEL, COR_GRAUPEL, 0.26, spec=0.2)
    ge.Ambient, ge.Diffuse = 0.2, 0.8
    _, gd = iso('Nucleo_Granizo_QGRAUP', 'QGRAUP_g_kg', TH_GRANIZO, COR_GRANIZO, 1.0, spec=0.4)
    gd.Ambient, gd.Diffuse = 0.12, 0.88

    view.EnableRenderOnInteraction = 0
    try:
        view.DepthPeeling = 1
        view.MaximumNumberOfPeels = 8
    except AttributeError:
        pass
    return view, tempestade


def camera(view, focal, azim_deg, elev_deg, dist, view_angle=30.0):
    a, e = math.radians(azim_deg), math.radians(elev_deg)
    view.CameraFocalPoint = focal
    view.CameraPosition = [focal[0] + dist * math.cos(e) * math.sin(a),
                           focal[1] - dist * math.cos(e) * math.cos(a),
                           focal[2] + dist * math.sin(e)]
    view.CameraViewUp = [0, 0, 1]
    view.CameraViewAngle = view_angle


# ============================================================== sobreposicao 2D
def projetar(cam, p):
    """Projecao perspectiva de um ponto 3D (coordenadas de cena) para pixels."""
    pos, foc, up, ang = cam
    sub = lambda a, b: [a[i] - b[i] for i in range(3)]
    dot = lambda a, b: sum(a[i] * b[i] for i in range(3))
    cross = lambda a, b: [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
                          a[0] * b[1] - a[1] * b[0]]
    norm = lambda a: [v / math.sqrt(dot(a, a)) for v in a]
    f = norm(sub(foc, pos))
    r = norm(cross(f, up))
    u = cross(r, f)
    v = sub(p, pos)
    zc = dot(v, f)
    k = (H / 2.0) / math.tan(math.radians(ang) / 2.0)
    return W / 2.0 + k * dot(v, r) / zc, H / 2.0 - k * dot(v, u) / zc


def fonte(sz, bold=False):
    return ImageFont.truetype(FONT_B if bold else FONT, sz)


def sobrepor(png, hora_utc, subtitulo=None, cam=None):
    im = Image.open(png).convert('RGBA')
    ov = Image.new('RGBA', im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    s = W / 1920.0

    # faixa de titulo com degrade
    for y in range(int(130 * s)):
        a = int(200 * (1 - y / (130 * s)) ** 1.4)
        d.line([(0, y), (W, y)], fill=(8, 12, 20, a))
    d.text((40 * s, 26 * s), 'Supercélula com granizo — Grande Florianópolis/SC',
           font=fonte(int(40 * s), True), fill=(245, 247, 250, 255))
    d.text((40 * s, 78 * s), subtitulo or 'WRF-ARW d03 (1 km) · Morrison 2-momentos · '
           f'alturas reais (PH+PHB) · exagero vertical: relevo {VE_T:g}×, atmosfera {VE_A:g}×'
           .replace('.', ','),
           font=fonte(int(22 * s)), fill=(190, 200, 215, 255))
    ft = fonte(int(44 * s), True)
    tw = d.textlength(hora_utc, font=ft)
    d.text((W - 40 * s - tw, 24 * s), hora_utc, font=ft, fill=(255, 255, 255, 255))
    d.text((W - 40 * s - d.textlength('29 ago 2026', font=fonte(int(22 * s))), 80 * s),
           '29 ago 2026', font=fonte(int(22 * s)), fill=(190, 200, 215, 255))

    # painel de legenda
    px, py, pw, ph = 36 * s, H - 392 * s, 490 * s, 356 * s
    d.rounded_rectangle([px, py, px + pw, py + ph], radius=int(14 * s), fill=(10, 15, 25, 185))
    y = py + 20 * s
    f1, f2 = fonte(int(22 * s), True), fonte(int(19 * s))
    for cor, op, nome, desc in [
        (COR_GRANIZO, 255, 'Núcleo de graupel/granizo', f'QGRAUP ≥ {TH_GRANIZO:g} g/kg'),
        (COR_GRAUPEL, 150, 'Envoltório de graupel', f'QGRAUP ≥ {TH_GRAUPEL:g} g/kg'),
        (COR_CHUVA, 200, 'Chuva', f'QRAIN ≥ {TH_CHUVA:g} g/kg'),
        (COR_NUVEM, 150, 'Nuvem (gotas + gelo + neve)', 'volume, QCLOUD+QICE+QSNOW'),
    ]:
        c = tuple(int(v * 255) for v in cor)
        d.rounded_rectangle([px + 20 * s, y + 4 * s, px + 58 * s, y + 34 * s], radius=int(6 * s),
                            fill=c + (op,), outline=(255, 255, 255, 90))
        d.text((px + 74 * s, y), nome, font=f1, fill=(240, 243, 248, 255))
        d.text((px + 74 * s, y + 26 * s), desc, font=f2, fill=(165, 178, 196, 255))
        y += 62 * s
    # barra da trilha de granizo
    d.text((px + 20 * s, y + 2 * s), 'Trilha de granizo no solo — diâmetro máx. (HAILCAST)',
           font=fonte(int(18 * s), True), fill=(240, 243, 248, 255))
    bx0, bx1, by = px + 20 * s, px + pw - 30 * s, y + 32 * s
    vmin, vmax = TRILHA[0][0], TRILHA[-1][0]
    stops = [((v - vmin) / (vmax - vmin), tuple(int(c * 255) for c in hx(h))) for v, h in TRILHA]
    for xi in range(int(bx0), int(bx1)):
        f = (xi - bx0) / (bx1 - bx0)
        for (f0, c0), (f1_, c1) in zip(stops[:-1], stops[1:]):
            if f0 <= f <= f1_:
                t = (f - f0) / (f1_ - f0)
                col = tuple(int(c0[k] + (c1[k] - c0[k]) * t) for k in range(3))
                break
        d.line([(xi, by), (xi, by + 16 * s)], fill=col + (255,))
    for v, _ in TRILHA:
        xt = bx0 + (v - vmin) / (vmax - vmin) * (bx1 - bx0)
        d.line([(xt, by + 16 * s), (xt, by + 22 * s)], fill=(200, 210, 225, 255))
        lab = f'{v:g}'
        d.text((xt - d.textlength(lab, font=f2) / 2, by + 24 * s), lab, font=f2,
               fill=(200, 210, 225, 255))
    d.text((bx1 + 8 * s, by - 2 * s), 'mm', font=f2, fill=(200, 210, 225, 255))

    # rotulo de Florianopolis projetado da cena 3D
    if cam is not None:
        sx, sy = projetar(cam, [FLN[0], FLN[1], FLN[2] + 0.4])
        fl = fonte(int(26 * s), True)
        lw = d.textlength('Florianópolis', font=fl)
        tx = sx + 14 * s if sx + 14 * s + lw < W - 20 * s else sx - 14 * s - lw
    if cam is not None and 0 <= sx <= W and 0 <= sy <= H:
        d.ellipse([sx - 7 * s, sy - 7 * s, sx + 7 * s, sy + 7 * s], fill=(255, 255, 255, 255),
                  outline=(20, 25, 35, 255), width=max(1, int(2 * s)))
        d.text((tx, sy - 16 * s), 'Florianópolis', font=fl, fill=(255, 255, 255, 255),
               stroke_width=max(1, int(3 * s)), stroke_fill=(15, 20, 30, 230))

    Image.alpha_composite(im, ov).convert('RGB').save(png)


# ============================================================== execucao
def hora_de(t):
    m = int(round(t * 60))
    return f'{m // 60:02d}:{m % 60:02d} UTC'


def renderizar(view, t, png, sub=None):
    view.ViewTime = t
    Render(view)
    SaveScreenshot(png, view, ImageResolution=[W, H])
    cam = (list(view.CameraPosition), list(view.CameraFocalPoint), list(view.CameraViewUp),
           view.CameraViewAngle)
    sobrepor(png, hora_de(t), sub, cam)


modo = sys.argv[1] if len(sys.argv) > 1 else 'still'
view, storm = montar_cena()
Render(view)   # 1o render reseta a camera no paraview.simple; fazer antes de posiciona-la
tempos = list(storm.TimestepValues)
t_pico = min(tempos, key=lambda x: abs(x - 19.5))

if modo == 'still':
    vistas = {
        'sul':      dict(focal=[0, 12, 8], azim=-10, elev=22, dist=175),
        'sudeste':  dict(focal=[-5, 26, 9], azim=-48, elev=20, dist=150),
        'zoom':     dict(focal=[-6, 30, 11], azim=-25, elev=10, dist=110),
    }
    for nome, v in vistas.items():
        camera(view, v['focal'], v['azim'], v['elev'], v['dist'])
        png = os.path.join(SAIDA, f'granizo_3d_pico_{nome}.png')
        renderizar(view, t_pico, png)
        print('salvo', png)
    camera(view, **{'focal': [-5, 28, 8], 'azim_deg': -48, 'elev_deg': 22, 'dist': 150})
    view.ViewTime = t_pico
    SaveState(os.path.join(SAIDA, 'granizo_3d.pvsm'))

elif modo == 'anim':
    for f in os.listdir(FRAMES):
        os.remove(os.path.join(FRAMES, f))
    n = len(tempos)
    for i, t in enumerate(tempos):
        # orbita lenta de 40 graus ao longo do evento, camera fixa no dominio
        az = -30 + 40 * i / max(n - 1, 1)
        camera(view, [0, 15, 7], az, 19, 225)
        renderizar(view, t, os.path.join(FRAMES, f'f_{i:03d}.png'))
        print(f'  {i + 1}/{n} {hora_de(t)}')
    ff = shutil.which('ffmpeg') or (r'C:\Users\haas\AppData\Local\Microsoft\WinGet\Packages'
                                    r'\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe'
                                    r'\ffmpeg-8.1.2-full_build\bin\ffmpeg.exe')
    mp4 = os.path.join(SAIDA, 'granizo_3d_evolucao.mp4')
    subprocess.run([ff, '-y', '-loglevel', 'error', '-framerate', '4',
                    '-i', os.path.join(FRAMES, 'f_%03d.png'),
                    '-vf', 'tpad=stop_mode=clone:stop_duration=2,format=yuv420p',
                    '-c:v', 'libx264', '-crf', '18', '-preset', 'slow', mp4], check=True)
    gif = os.path.join(SAIDA, 'granizo_3d_evolucao.gif')
    subprocess.run([ff, '-y', '-loglevel', 'error', '-framerate', '4',
                    '-i', os.path.join(FRAMES, 'f_%03d.png'), '-vf',
                    'scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=192[p];'
                    '[b][p]paletteuse=dither=sierra2_4a', '-loop', '0', gif], check=True)
    print('salvo', mp4, gif)
