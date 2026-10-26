"""
Prepara os dados da supercelula (WRF d03) para visualizacao 3D no ParaView.

- Interpola os campos dos niveis eta para altura geometrica real (PH+PHB, km MSL)
  e grava a grade ja na coordenada vertical da cena (exagero vertical aplicado):
    relevo com VE_T, atmosfera com VE_A; perto do solo a atmosfera acompanha o
    relevo e a diferenca decai linearmente ate ZD km acima do terreno.
- Relevo (HGT) + trilha acumulada de granizo na superficie (HAILCAST_DIAM_MAX, mm).
- Limites municipais/estaduais reprojetados na LCC do WRF (lon_0 = STAND_LON),
  assentados sobre o relevo.

Rodar com:  "C:/Program Files/ParaView 6.2.0/bin/pvpython.exe" preparar_dados_granizo.py
"""
import os
import json
import struct
import numpy as np
import netCDF4
import vtk
from vtk.util import numpy_support as ns

BASE = r'C:\gis4wrf\projects\Floripa'
WRFOUT = os.path.join(BASE, r'run_wrf\wrfout_d03_2026-08-29_12_00_00')
SHP_DIR = os.path.join(BASE, 'shp_ibge')
OUT = os.path.join(BASE, r'viz_granizo_v2\dados')
os.makedirs(OUT, exist_ok=True)

VE_T, VE_A, ZD = 3.5, 2.0, 6.0               # exagero do relevo, da atmosfera, decaimento (km)
ZS = np.arange(0.0, 18.0 * VE_A + 1e-4, 0.5)  # niveis da cena (0.5 = 250 m na atmosfera)
T0, T1 = 24, 66                             # 16:00Z .. 23:00Z (saida a cada 10 min)


def to_vtk(arr, name):
    v = ns.numpy_to_vtk(np.ascontiguousarray(arr, dtype=np.float32).ravel(), deep=True)
    v.SetName(name)
    return v


def scene_to_height(zs, hgt):
    """Inverte zs = VE_A*z + (VE_T-VE_A)*h*max(0, 1-(z-h)/ZD) -> z fisico (km MSL)."""
    c = VE_T - VE_A
    z = (zs - c * hgt * (1.0 + hgt / ZD)) / (VE_A - c * hgt / ZD)
    return np.where(z <= hgt + ZD, z, zs / VE_A)


def interp_to_heights(f, z, hgt):
    """f, z: (nk, ny, nx); z em km MSL. Interpolacao linear para os niveis da cena."""
    nk = z.shape[0]
    out = np.zeros((len(ZS),) + z.shape[1:], dtype=np.float32)
    for i, zsc in enumerate(ZS):
        zt = scene_to_height(zsc, hgt)
        k1 = np.clip((z < zt[None]).sum(axis=0), 1, nk - 1)
        k0 = k1 - 1
        z0 = np.take_along_axis(z, k0[None], 0)[0]
        z1 = np.take_along_axis(z, k1[None], 0)[0]
        f0 = np.take_along_axis(f, k0[None], 0)[0]
        f1 = np.take_along_axis(f, k1[None], 0)[0]
        w = np.clip((zt - z0) / (z1 - z0), 0.0, 1.0)
        val = f0 + (f1 - f0) * w
        val[zt < hgt] = 0.0                  # abaixo do relevo
        out[i] = val
    return out


def read_shp_rings(path):
    """Leitor minimo de .shp (Polygon/PolyLine, 2D/Z/M) -> lista de arrays (n,2) lon/lat."""
    rings = []
    with open(path, 'rb') as fh:
        data = fh.read()
    pos = 100
    while pos < len(data):
        _, clen = struct.unpack('>ii', data[pos:pos + 8])
        rec = data[pos + 8: pos + 8 + clen * 2]
        pos += 8 + clen * 2
        stype = struct.unpack('<i', rec[:4])[0]
        if stype not in (3, 5, 13, 15, 23, 25):
            continue
        nparts, npts = struct.unpack('<ii', rec[36:44])
        parts = list(struct.unpack('<%di' % nparts, rec[44:44 + 4 * nparts])) + [npts]
        xy = np.frombuffer(rec, dtype='<f8', count=2 * npts, offset=44 + 4 * nparts).reshape(-1, 2)
        for a, b in zip(parts[:-1], parts[1:]):
            rings.append(xy[a:b])
    return rings


def write_xml(writer, data, fname):
    writer.SetFileName(os.path.join(OUT, fname))
    writer.SetInputData(data)
    writer.SetCompressorTypeToZLib()
    writer.Write()


with netCDF4.Dataset(WRFOUT) as ds:
    ga = ds.getncattr
    V = ds.variables
    times = [b''.join(t).decode() for t in V['Times'][:]]
    hgt_m = np.array(V['HGT'][0], dtype=np.float64)
    hgt = hgt_m / 1000.0
    land = np.array(V['LANDMASK'][0])
    ny, nx = hgt.shape
    dx = ga('DX') / 1000.0
    xs = (np.arange(nx) - (nx - 1) / 2.0) * dx
    ys = (np.arange(ny) - (ny - 1) / 2.0) * dx

    # LCC esferica do WRF, lon_0 = STAND_LON (nao CEN_LON)
    R = 6370000.0
    p1, p2 = np.radians(ga('TRUELAT1')), np.radians(ga('TRUELAT2'))
    if abs(p1 - p2) < 1e-8:
        ncone = np.sin(p1)
    else:
        ncone = (np.log(np.cos(p1) / np.cos(p2)) /
                 np.log(np.tan(np.pi / 4 + p2 / 2) / np.tan(np.pi / 4 + p1 / 2)))
    Fc = np.cos(p1) * np.tan(np.pi / 4 + p1 / 2) ** ncone / ncone
    lon0 = np.radians(ga('STAND_LON'))

    def lcc(lon, lat):
        th = ncone * (np.radians(lon) - lon0)
        r = R * Fc / np.tan(np.pi / 4 + np.radians(lat) / 2) ** ncone
        return r * np.sin(th) / 1e3, -r * np.cos(th) / 1e3

    gx, gy = lcc(np.array(V['XLONG'][0]), np.array(V['XLAT'][0]))
    xoff = gx.mean() - xs.mean()
    yoff = gy.mean() - ys.mean()
    err = max(np.abs(gx - xoff - xs[None, :]).max(), np.abs(gy - yoff - ys[:, None]).max())
    print(f'Projecao LCC: erro maximo vs grade = {err * 1000:.1f} m')

    def project(lon, lat):
        x, y = lcc(lon, lat)
        return x - xoff, y - yoff

    def terrain_at(x, y):
        fi = np.clip((x - xs[0]) / dx, 0, nx - 1.001)
        fj = np.clip((y - ys[0]) / dx, 0, ny - 1.001)
        i, j = fi.astype(int), fj.astype(int)
        wi, wj = fi - i, fj - j
        return ((1 - wi) * (1 - wj) * hgt[j, i] + wi * (1 - wj) * hgt[j, i + 1] +
                (1 - wi) * wj * hgt[j + 1, i] + wi * wj * hgt[j + 1, i + 1])

    # ------------------------------------------------ limites (municipios, estados, costa)
    xmin, xmax, ymin, ymax = xs[0], xs[-1], ys[0], ys[-1]

    def lines_vtp(shp, fname, lift_km):
        pts, cells = vtk.vtkPoints(), vtk.vtkCellArray()
        for ring in read_shp_rings(os.path.join(SHP_DIR, shp)):
            x, y = project(ring[:, 0], ring[:, 1])
            inside = (x >= xmin) & (x <= xmax) & (y >= ymin) & (y <= ymax)
            idx = np.flatnonzero(inside)
            if idx.size < 2:
                continue
            breaks = np.flatnonzero(np.diff(idx) > 1)
            for seg in np.split(idx, breaks + 1):
                if seg.size < 2:
                    continue
                sx, sy = x[seg], y[seg]
                sz = VE_T * (terrain_at(sx, sy) + lift_km)
                pl = vtk.vtkPolyLine()
                pl.GetPointIds().SetNumberOfIds(seg.size)
                for k in range(seg.size):
                    pl.GetPointIds().SetId(k, pts.InsertNextPoint(sx[k], sy[k], sz[k]))
                cells.InsertNextCell(pl)
        pd = vtk.vtkPolyData()
        pd.SetPoints(pts)
        pd.SetLines(cells)
        write_xml(vtk.vtkXMLPolyDataWriter(), pd, fname)
        print(f'  {fname}: {cells.GetNumberOfCells()} linhas')

    print('Limites geograficos...')
    lines_vtp('SC_Municipios_2022.shp', 'municipios.vtp', 0.03)
    lines_vtp('BR_Estados.shp', 'estados.vtp', 0.04)
    lines_vtp('America_do_Sul.shp', 'costa.vtp', 0.04)

    fx, fy = project(np.array([-48.548]), np.array([-27.595]))   # Florianopolis (centro)
    meta = {'florianopolis_km': [float(fx[0]), float(fy[0]), float(VE_T * terrain_at(fx, fy)[0])],
            'VE_T': VE_T, 'VE_A': VE_A, 'ZD_km': ZD}

    # ------------------------------------------------ relevo + trilha de granizo (serie)
    X, Y = np.meshgrid(xs, ys)
    surf_pts = np.column_stack([X.ravel(), Y.ravel(), VE_T * hgt.ravel()]).astype(np.float32)
    elev = np.where(land > 0.5, np.maximum(hgt_m, 1.0), -100.0)   # oceano = -100

    hail_hist = np.array(V['HAILCAST_DIAM_MAX'][:T1 + 1], dtype=np.float32)
    swath = np.maximum.accumulate(hail_hist, axis=0)   # maximo acumulado desde 12Z

    terrain_series, storm_series, track = [], [], []
    for t in range(T0, T1 + 1):
        tag = times[t][11:16].replace(':', '')
        hours = 12.0 + t / 6.0

        sg = vtk.vtkStructuredGrid()
        sg.SetDimensions(nx, ny, 1)
        p = vtk.vtkPoints()
        p.SetData(ns.numpy_to_vtk(surf_pts, deep=True))
        sg.SetPoints(p)
        sg.GetPointData().AddArray(to_vtk(elev, 'Elevacao_m'))
        sg.GetPointData().AddArray(to_vtk(swath[t], 'Granizo_diam_max_mm'))
        sg.GetPointData().AddArray(to_vtk(hail_hist[t], 'Granizo_diam_inst_mm'))
        fn = f'relevo_{tag}z.vts'
        write_xml(vtk.vtkXMLStructuredGridWriter(), sg, fn)
        terrain_series.append({'name': fn, 'time': hours})

        # --- campos 3D em altura real
        z = ((V['PH'][t] + V['PHB'][t]) / 9.81 / 1000.0).astype(np.float32)
        zm = 0.5 * (z[:-1] + z[1:])
        wv = V['W'][t]
        fields = [
            ('QGRAUP_g_kg', V['QGRAUP'][t] * 1000.0),
            ('QRAIN_g_kg', V['QRAIN'][t] * 1000.0),
            ('QNUVEM_g_kg', (V['QCLOUD'][t] + V['QICE'][t] + V['QSNOW'][t]) * 1000.0),
            ('REFL_dBZ', V['REFL_10CM'][t]),
            ('W_m_s', 0.5 * (wv[:-1] + wv[1:])),
        ]
        img = vtk.vtkImageData()
        img.SetDimensions(nx, ny, len(ZS))
        img.SetOrigin(xs[0], ys[0], 0.0)
        img.SetSpacing(dx, dx, ZS[1] - ZS[0])
        qgmax = 0.0
        for name, fld in fields:
            g = interp_to_heights(np.asarray(fld, dtype=np.float32), zm, hgt)
            if name == 'REFL_dBZ':
                g[g == 0.0] = -30.0
            img.GetPointData().AddArray(to_vtk(g, name))
            if name == 'QGRAUP_g_kg':
                col = g.max(axis=0)
                qgmax = float(col.max())
                if qgmax > 2.0:
                    j, i = np.unravel_index(np.argmax(col), col.shape)
                    track.append([times[t], float(xs[i]), float(ys[j]), qgmax])
        fn = f'tempestade_{tag}z.vti'
        write_xml(vtk.vtkXMLImageDataWriter(), img, fn)
        storm_series.append({'name': fn, 'time': hours})
        print(f'  {times[t]}  QGRAUP max {qgmax:5.1f} g/kg  '
              f'HAILCAST max {float(hail_hist[t].max()):5.1f} mm')

for fn, ser in [('relevo.vts.series', terrain_series), ('tempestade.vti.series', storm_series)]:
    with open(os.path.join(OUT, fn), 'w', encoding='utf-8') as fh:
        json.dump({'file-series-version': '1.0', 'files': ser}, fh, indent=1)

meta['trilha_qgraup_max'] = track
meta['hailcast_max_mm'] = float(swath[-1].max())
with open(os.path.join(OUT, 'meta.json'), 'w', encoding='utf-8') as fh:
    json.dump(meta, fh, indent=1)
print('OK ->', OUT)
