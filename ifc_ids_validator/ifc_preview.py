"""Fast, read-only IFC overview: sampled coarse volumes, no tessellation/CSG."""
from __future__ import annotations

import base64
import io
import math
import multiprocessing
import os
import queue
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from ifc_ids_validator.app_icon import set_app_icon

BACKGROUND = "#EDF2F9"


# This is an overview, deliberately bounded independently of IFC complexity.
MAX_PREVIEW_ELEMENTS = 600
MAX_POINT_SAMPLES = 128
MAX_GEOMETRY_NODES = 256
CACHE_VERSION = "coarse-volume-2"


def _even_sample(values, count):
    if len(values) <= count:
        return list(values)
    if count == 1:
        return [values[len(values) // 2]]
    return [values[index * (len(values) - 1) // (count - 1)] for index in range(count)]


def _select_overview_elements(elements):
    """Spread a small sample across classes and export order (usually floors)."""
    groups = {}
    decorative = ("IfcReinforcing", "IfcFastener", "IfcMechanicalFastener", "IfcFurnishing", "IfcDiscreteAccessory")
    for element in elements:
        kind = element.is_a()
        if not kind.startswith(decorative):
            groups.setdefault(kind, []).append(element)
    if not groups:
        for element in elements:
            groups.setdefault(element.is_a(), []).append(element)
    if sum(map(len, groups.values())) <= MAX_PREVIEW_ELEMENTS:
        return [element for group in groups.values() for element in group]
    # Walls/slabs/roofs preserve the outline; engineering-only models keep pipes,
    # ducts and equipment, with no mandatory architectural class filter.
    major = ("IfcWall", "IfcSlab", "IfcRoof", "IfcBeam", "IfcColumn", "IfcMember", "IfcFooting", "IfcPlate")
    weights = {kind: math.sqrt(len(group)) * (3 if kind.startswith(major) else 1)
               for kind, group in groups.items()}
    # A single large slab/roof must not disappear amongst thousands of walls.
    first_classes = sorted(groups, key=lambda kind: weights[kind], reverse=True)[:MAX_PREVIEW_ELEMENTS]
    quotas = {kind: int(kind in first_classes) for kind in groups}
    for _ in range(MAX_PREVIEW_ELEMENTS - sum(quotas.values())):
        available = [kind for kind in groups if quotas[kind] < len(groups[kind])]
        if not available:
            break
        kind = max(available, key=lambda name: weights[name] / (quotas[name] + 1))
        quotas[kind] += 1
    return [element for kind, group in groups.items() for element in _even_sample(group, quotas[kind])
            if quotas[kind]]


class _CoarseGeometry:
    """Read bounds from IFC parameters; never invoke the geometry/CSG kernel."""
    def __init__(self):
        import numpy as np
        from ifcopenshell.util import placement
        self.np, self.placement = np, placement
        self.cache, self.placements = {}, {}
        self.visits = 0

    def corners(self, low, high):
        return self.np.asarray([[x, y, z] for x in (low[0], high[0])
                               for y in (low[1], high[1]) for z in (low[2], high[2])], dtype=float)

    def points_bounds(self, coordinates):
        coordinates = _even_sample(coordinates, MAX_POINT_SAMPLES)
        if not coordinates:
            return None
        points = self.np.asarray(coordinates, dtype=float)
        if points.ndim != 2 or points.shape[1] not in (2, 3):
            return None
        if points.shape[1] == 2:
            points = self.np.column_stack((points, self.np.zeros(len(points))))
        points = points[self.np.isfinite(points).all(axis=1)]
        return (points.min(axis=0), points.max(axis=0)) if len(points) else None

    def merge(self, bounds):
        bounds = [value for value in bounds if value is not None]
        if not bounds:
            return None
        return self.np.min([value[0] for value in bounds], axis=0), self.np.max([value[1] for value in bounds], axis=0)

    def transform(self, bounds, matrix):
        if bounds is None or matrix is None:
            return bounds
        corners = self.corners(*bounds)
        points = corners @ matrix[:3, :3].T + matrix[:3, 3]
        return points.min(axis=0), points.max(axis=0)

    def axis(self, position):
        return self.placement.get_axis2placement(position) if position else self.np.eye(4)

    def local_placement(self, placement, depth=0):
        if placement is None:
            return self.np.eye(4)
        key = placement.id()
        if key not in self.placements:
            if depth > 40 or not placement.is_a("IfcLocalPlacement"):
                raise ValueError("Unsupported placement")
            self.placements[key] = (self.local_placement(placement.PlacementRelTo, depth + 1)
                                    @ self.axis(placement.RelativePlacement))
        return self.placements[key]

    def bounds(self, item, depth=0):
        if item is None or depth > 12 or self.visits >= MAX_GEOMETRY_NODES:
            return None
        key = item.id()
        if key in self.cache:
            return self.cache[key]
        self.visits += 1
        try:
            result = self._bounds(item, depth)
        except (AttributeError, TypeError, ValueError, IndexError, RuntimeError, ZeroDivisionError):
            result = None
        self.cache[key] = result
        return result

    def _bounds(self, item, depth):
        np = self.np
        kind = item.is_a()
        child = lambda value: self.bounds(value, depth + 1)
        if kind == "IfcBoundingBox":
            low = np.array(item.Corner.Coordinates, dtype=float)
            return low, low + [item.XDim, item.YDim, item.ZDim]
        if item.is_a("IfcBooleanResult"):
            # No openings/clipping calculations: retain the host's gross volume.
            first = child(item.FirstOperand)
            return self.merge([first, child(item.SecondOperand)]) if item.Operator == "UNION" else first
        if kind == "IfcMappedItem":
            return self.transform(child(item.MappingSource.MappedRepresentation),
                                  self.placement.get_mappeditem_transformation(item))
        if item.is_a("IfcExtrudedAreaSolid"):
            profile = child(item.SweptArea)
            if profile is None:
                return None
            direction = np.array(item.ExtrudedDirection.DirectionRatios, dtype=float)
            direction /= max(float(np.linalg.norm(direction)), 1e-12)
            shift = direction * item.Depth
            swept = (np.minimum(profile[0], profile[0] + shift), np.maximum(profile[1], profile[1] + shift))
            return self.transform(swept, self.axis(item.Position))
        if item.is_a("IfcSweptDiskSolid"):
            bounds = child(item.Directrix)
            return (bounds[0] - item.Radius, bounds[1] + item.Radius) if bounds else None
        if item.is_a("IfcArbitraryClosedProfileDef"):
            return child(item.OuterCurve)
        if item.is_a("IfcParameterizedProfileDef"):
            if item.is_a("IfcRectangleProfileDef"):
                width, height = item.XDim, item.YDim
            elif item.is_a("IfcCircleProfileDef"):
                width = height = item.Radius * 2
            elif kind == "IfcEllipseProfileDef":
                width, height = item.SemiAxis1 * 2, item.SemiAxis2 * 2
            else:
                width = getattr(item, "OverallWidth", None) or getattr(item, "Width", None)
                height = getattr(item, "OverallDepth", None) or getattr(item, "Depth", None)
                if not width or not height:
                    return None
            return self.transform((np.array([-width/2, -height/2, 0]), np.array([width/2, height/2, 0])),
                                  self.axis(item.Position))
        if kind == "IfcCartesianPoint":
            return self.points_bounds([item.Coordinates])
        if kind in ("IfcCartesianPointList2D", "IfcCartesianPointList3D"):
            return self.points_bounds(item.CoordList)
        if kind == "IfcIndexedPolyCurve":
            return child(item.Points)
        if kind in ("IfcPolyline", "IfcPolyLoop"):
            return self.points_bounds([point.Coordinates for point in _even_sample(item.Points, MAX_POINT_SAMPLES)])
        if kind in ("IfcCircle", "IfcEllipse"):
            x = item.Radius if kind == "IfcCircle" else item.SemiAxis1
            y = item.Radius if kind == "IfcCircle" else item.SemiAxis2
            return self.transform((np.array([-x,-y,0]), np.array([x,y,0])), self.axis(item.Position))
        if item.is_a("IfcTessellatedFaceSet"):
            # Ignore polygon connectivity altogether; use sampled vertices only.
            return child(item.Coordinates)
        if item.is_a("IfcManifoldSolidBrep"):
            return child(item.Outer)
        if kind == "IfcBlock":
            return self.transform((np.zeros(3), np.array([item.XLength,item.YLength,item.ZLength])), self.axis(item.Position))
        if kind == "IfcRightCircularCylinder":
            r = item.Radius
            return self.transform((np.array([-r,-r,0]), np.array([r,r,item.Height])), self.axis(item.Position))
        if kind == "IfcSphere":
            return self.transform((np.full(3,-item.Radius), np.full(3,item.Radius)), self.axis(item.Position))
        # Deliberately bounded traversal of faceted BReps/shells and curve sets.
        links = {"IfcFacetedBrep": "Outer", "IfcAdvancedBrep": "Outer", "IfcClosedShell": "CfsFaces",
                 "IfcOpenShell": "CfsFaces", "IfcFace": "Bounds", "IfcAdvancedFace": "Bounds",
                 "IfcFaceBound": "Bound", "IfcFaceOuterBound": "Bound", "IfcShellBasedSurfaceModel": "SbsmBoundary",
                 "IfcFaceBasedSurfaceModel": "FbsmFaces", "IfcConnectedFaceSet": "CfsFaces",
                 "IfcShapeRepresentation": "Items", "IfcRepresentation": "Items",
                 "IfcGeometricCurveSet": "Elements", "IfcGeometricSet": "Elements",
                 "IfcCompositeCurve": "Segments", "IfcCompositeCurveSegment": "ParentCurve", "IfcTrimmedCurve": "BasisCurve"}
        attribute = links.get(kind)
        if attribute:
            values = getattr(item, attribute)
            if isinstance(values, (tuple, list)):
                return self.merge(child(value) for value in _even_sample(values, 32))
            return child(values)
        return None

    def element_bounds(self, element):
        self.visits = 0
        reps = element.Representation.Representations
        selected = [rep for rep in reps if rep.RepresentationIdentifier == "Box"]
        if not selected:
            selected = [rep for rep in reps if rep.RepresentationIdentifier == "Body"]
        if not selected:
            selected = [rep for rep in reps if getattr(rep.ContextOfItems, "CoordinateSpaceDimension", 3) == 3]
        return self.merge(self.bounds(rep) for rep in _even_sample(selected, 4))


def _preview_cache_path(path):
    import hashlib
    from ifc_ids_validator.config import CONF_DIR
    path = Path(path).resolve()
    stat = path.stat()
    key = f"{CACHE_VERSION}|{MAX_PREVIEW_ELEMENTS}|{path}|{stat.st_size}|{stat.st_mtime_ns}"
    return CONF_DIR / "preview_cache" / (hashlib.sha256(key.encode()).hexdigest() + ".npz")


def _read_preview_cache(path):
    import numpy as np
    try:
        with np.load(path, allow_pickle=False) as data:
            mesh = {key: data[key] for key in data.files}
        for key in ("elements", "candidates", "total", "markers"):
            mesh[key] = int(mesh[key])
        mesh["radius"] = float(mesh["radius"])
        if not 0 < mesh["elements"] <= MAX_PREVIEW_ELEMENTS or len(mesh["triangles"]) != mesh["elements"] * 12:
            return None
        if mesh["triangles"].shape[1:] != (3, 3) or mesh["colours"].shape != (len(mesh["triangles"]), 3):
            return None
        if not np.isfinite(mesh["triangles"]).all() or not np.isfinite(mesh["colours"]).all():
            return None
        if mesh["size"].shape != (3,) or not np.isfinite(mesh["size"]).all() or not np.isfinite(mesh["radius"]) or mesh["radius"] <= 0:
            return None
        return mesh
    except Exception:
        # Derived cache is disposable; corrupt/unavailable entries are rebuilt.
        return None


def _save_preview_cache(path, mesh):
    import numpy as np
    import tempfile
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            np.savez_compressed(handle, **mesh)
        os.replace(temporary, path)
        # Keep disk use bounded, independently of how many projects are opened.
        entries = sorted(path.parent.glob("*.npz"), key=lambda entry: entry.stat().st_mtime_ns, reverse=True)
        for old in entries[24:]:
            old.unlink(missing_ok=True)
    except OSError:
        pass
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def load_preview_mesh(path, progress=lambda text: None):
    import numpy as np
    cache = _preview_cache_path(path)
    mesh = _read_preview_cache(cache)
    if mesh is not None:
        progress("Быстрый предпросмотр из кэша…")
        return mesh
    import ifcopenshell
    from ifcopenshell.util.unit import calculate_unit_scale

    progress("Чтение IFC для упрощённого вида…")
    model = ifcopenshell.open(str(path))
    elements = [item for item in model.by_type("IfcElement")
                if not item.is_a("IfcFeatureElementSubtraction") and item.Representation]
    if not elements:
        raise ValueError("В модели нет элементов с трёхмерной геометрией.")
    selected = _select_overview_elements(elements)
    geometry = _CoarseGeometry()
    scale = calculate_unit_scale(model)
    corners, colours, markers = [], [], 0
    # Twelve flat triangles per element: complexity never depends on its mesh.
    faces = np.array([[0,1,3],[0,3,2],[4,6,7],[4,7,5],[0,4,5],[0,5,1],
                      [2,3,7],[2,7,6],[0,2,6],[0,6,4],[1,5,7],[1,7,3]])
    progress(f"Упрощённые объёмы: до {len(selected)} элементов…")
    for index, element in enumerate(selected):
        try:
            bounds = geometry.element_bounds(element)
            matrix = geometry.local_placement(element.ObjectPlacement)
            marker = bounds is None
            if marker:
                # Unknown representation: show its placement as an orange marker,
                # rather than wait for CSG or claim to have reconstructed its form.
                half = 0.15 / scale
                bounds = (np.full(3,-half), np.full(3,half))
            points = geometry.corners(*bounds) @ matrix[:3,:3].T + matrix[:3,3]
            points *= scale
            if not np.isfinite(points).all():
                continue
            corners.append(points)
            kind = element.is_a()
            colour = (0.90,0.64,0.32) if marker else (0.57,0.68,0.80) if kind.startswith(("IfcPipe","IfcDuct","IfcCable","IfcFlow")) else (0.68,0.73,0.81)
            colours.append(np.tile(colour, (12,1)))
            markers += int(marker)
        except (AttributeError, TypeError, ValueError, RuntimeError, RecursionError):
            continue
        if (index + 1) % 100 == 0:
            progress(f"Упрощено: {index + 1} / {len(selected)}")
    if not corners:
        raise ValueError("Не найдены объёмы или позиции элементов для предпросмотра.")
    vertices = np.stack(corners)
    low, high = vertices.min(axis=(0,1)), vertices.max(axis=(0,1))
    origin = (low + high) / 2
    triangles = (vertices[:,faces].reshape(-1,3,3) - origin).astype(np.float32)
    normals = np.cross(triangles[:,1]-triangles[:,0], triangles[:,2]-triangles[:,0])
    normals /= np.maximum(np.linalg.norm(normals,axis=1)[:,None], 1e-12)
    light = np.array([0.35,-0.45,0.82]); light /= np.linalg.norm(light)
    shading = 0.55 + 0.45 * np.abs(normals @ light)
    colours = np.clip(np.concatenate(colours) * shading[:,None], 0, 1).astype(np.float32)
    mesh = {"triangles": triangles, "colours": colours, "size": high-low,
            "radius": max(float(np.max(high-low)) * 0.6, 0.001),
            "elements": len(corners), "candidates": len(selected), "total": len(elements), "markers": markers}
    # Do not cache a model that changed while it was being read.
    try:
        if _preview_cache_path(path) == cache:
            _save_preview_cache(cache, mesh)
    except OSError:
        pass
    return mesh


class PreviewRenderer:
    """Agg produces PNG frames; neither Matplotlib nor geometry touches the UI."""
    def __init__(self, mesh):
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from mpl_toolkits.mplot3d.art3d import Poly3DCollection
        self.mesh = mesh
        self.figure = Figure(figsize=(8, 6), dpi=100, facecolor=BACKGROUND)
        self.canvas = FigureCanvasAgg(self.figure)
        self.axes = self.figure.add_axes([0, 0, 1, 1], projection="3d", facecolor=BACKGROUND)
        self.axes.set_axis_off()
        self.axes.set_box_aspect((1, 1, 1), zoom=1.5)
        self.axes.set_proj_type("ortho")
        self.axes.add_collection3d(Poly3DCollection(mesh["triangles"], facecolors=mesh["colours"],
                                                   edgecolors="none", linewidths=0, antialiased=False))

    def render(self, view, width, height):
        import numpy as np
        width, height = max(100, int(width)), max(100, int(height))
        self.figure.set_size_inches(width / 100, height / 100, forward=False)
        self.axes.view_init(elev=view["elevation"], azim=view["azimuth"])
        radius = self.mesh["radius"] * view["zoom"]
        centre = np.asarray(view["centre"]) * self.mesh["radius"]
        for setter, coordinate in zip((self.axes.set_xlim3d, self.axes.set_ylim3d, self.axes.set_zlim3d), centre):
            setter(coordinate - radius, coordinate + radius)
        png = io.BytesIO()
        self.canvas.print_png(png)
        return png.getvalue()


def preview_worker(path, commands, events):
    try:
        # Dependency errors are contained in the preview; validation remains usable.
        import matplotlib  # noqa: F401
        mesh = load_preview_mesh(path, lambda text: events.put(("status", text)))
        renderer = PreviewRenderer(mesh)
        events.put(("ready", {key: mesh[key] for key in ("size", "elements", "candidates", "total", "markers")}))
        while True:
            command = commands.get()
            # Render only the newest camera state after fast mouse movements.
            try:
                while True:
                    command = commands.get_nowait()
            except queue.Empty:
                pass
            revision, view, width, height = command
            events.put(("frame", revision, renderer.render(view, width, height)))
    except ImportError as error:
        events.put(("error", "Для предпросмотра нужна библиотека Matplotlib. "
                    "Установите зависимости из requirements-preview.txt и перезапустите программу.\n"
                    f"{error}"))
    except Exception as error:
        events.put(("error", f"Не удалось открыть предпросмотр:\n{error}"))


def default_view():
    return {"azimuth": -55.0, "elevation": 25.0, "zoom": 1.0, "centre": [0.0, 0.0, 0.0]}


class IFCPreview(tk.Toplevel):
    def __init__(self, master, path):
        super().__init__(master)
        set_app_icon(self)
        self.path = str(path)
        self.title(f"Быстрый предпросмотр IFC — {Path(path).name}")
        self.configure(bg=BACKGROUND)
        width, height = min(1000, self.winfo_screenwidth() - 80), min(760, self.winfo_screenheight() - 100)
        self.geometry(f"{width}x{height}")
        self.minsize(480, 360)
        self.transient(master)  # modeless: the model list and validation remain accessible
        self.closed = False
        self.ready = False
        self.view = default_view()
        self.revision = 0
        self.frame_revision = -1
        self._render_timer = self._poll_timer = None
        self._drag = None
        self._image = None
        self.process = None
        self.commands = self.events = None
        bar = tk.Frame(self, bg="white", padx=14, pady=10); bar.pack(fill="x")
        tk.Label(bar, text=Path(path).name, bg="white", fg="#172A43",
                 font=("Segoe UI Semibold", 11)).pack(side="left")
        self.fit_button = ttk.Button(bar, text="Вписать", command=self.fit, state="disabled")
        self.fit_button.pack(side="right")
        self.canvas = tk.Canvas(self, bg=BACKGROUND, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self._message = self.canvas.create_text(30, 30, anchor="nw", fill="#172A43",
                                               text="Загрузка упрощённого вида…", font=("Segoe UI", 11), width=700)
        self._frame_item = self.canvas.create_image(0, 0, anchor="nw")
        self.status = tk.StringVar(value="Чтение IFC…")
        tk.Label(self, textvariable=self.status, bg="white", fg="#172A43", anchor="w",
                 padx=14, pady=8, wraplength=900).pack(fill="x")
        tk.Label(self, text="Левая кнопка — вращение  ·  Средняя / правая — перемещение  ·  Колесо — масштаб",
                 bg=BACKGROUND, fg="#738197", font=("Segoe UI", 9), pady=6).pack(fill="x")
        self.canvas.bind("<Configure>", lambda event: self.schedule_render())
        for button in (1, 2, 3):
            self.canvas.bind(f"<ButtonPress-{button}>", self._press)
            self.canvas.bind(f"<B{button}-Motion>", self._motion)
            self.canvas.bind(f"<ButtonRelease-{button}>", self._release)
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Button-4>", lambda event: self._zoom(0.85))
        self.canvas.bind("<Button-5>", lambda event: self._zoom(1 / 0.85))
        self.bind("<Escape>", lambda event: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        try:
            context = multiprocessing.get_context("spawn")
            self.commands, self.events = context.Queue(), context.Queue()
            self.process = context.Process(target=preview_worker, args=(self.path, self.commands, self.events), daemon=True)
            self.process.start()
            self._poll_timer = self.after(80, self._poll)
        except Exception as error:
            self._show_error(f"Не удалось запустить предпросмотр:\n{error}")

    def _show_error(self, text):
        self.ready = False
        self.fit_button.configure(state="disabled")
        self.canvas.itemconfigure(self._message, text=text)
        self.status.set("Предпросмотр недоступен. Можно выбрать другую модель.")

    def _poll(self):
        self._poll_timer = None
        if self.closed:
            return
        latest_frame = None
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "status":
                    self.status.set(event[1]); self.canvas.itemconfigure(self._message, text=event[1])
                elif event[0] == "ready":
                    self.info = event[1]
                    self.ready = True
                    self.fit_button.configure(state="normal")
                    self.status.set("Упрощённый вид готов. Подготовка изображения…")
                    self.schedule_render()
                elif event[0] == "frame":
                    latest_frame = event
                elif event[0] == "error":
                    self._show_error(event[1])
        except queue.Empty:
            pass
        if latest_frame and latest_frame[1] >= self.frame_revision:
            self.frame_revision = latest_frame[1]
            self._image = tk.PhotoImage(master=self, data=base64.b64encode(latest_frame[2]))
            self.canvas.itemconfigure(self._frame_item, image=self._image)
            self.canvas.itemconfigure(self._message, text="")
            size = " × ".join(f"{value:.2f}" for value in self.info["size"])
            message = f"Упрощённый вид: {self.info['elements']} из {self.info['total']} элементов  ·  Габариты вида ≈ {size} м"
            if self.info["markers"]:
                message += f"  ·  Условные позиции: {self.info['markers']}"
            if self.frame_revision < self.revision:
                message += "  ·  Обновление вида…"
            self.status.set(message)
        if self.process is not None and not self.process.is_alive():
            if self.ready:
                self._show_error("Процесс предпросмотра завершился. Выберите модель повторно.")
            elif "недоступен" not in self.status.get():
                self._show_error(f"Процесс предпросмотра завершился (код {self.process.exitcode}).")
            return
        self._poll_timer = self.after(80, self._poll)

    def schedule_render(self):
        if self.closed or not self.ready or self._render_timer is not None:
            return
        self._render_timer = self.after(50, self._request_render)

    def _request_render(self):
        self._render_timer = None
        if self.closed or not self.ready:
            return
        self.revision += 1
        # Snapshot: subsequent mouse events must not mutate a queued camera state.
        view = dict(self.view, centre=list(self.view["centre"]))
        self.commands.put((self.revision, view, self.canvas.winfo_width(), self.canvas.winfo_height()))

    def fit(self):
        self.view = default_view()
        self.schedule_render()

    def _press(self, event):
        if self.ready:
            self._drag = (event.x, event.y, event.num)

    def _motion(self, event):
        if not self.ready or self._drag is None:
            return
        x, y, button = self._drag
        dx, dy = event.x - x, event.y - y
        self._drag = (event.x, event.y, button)
        if button == 1:
            self.view["azimuth"] -= dx * 0.5
            self.view["elevation"] = max(-89, min(89, self.view["elevation"] + dy * 0.5))
        else:
            az = math.radians(self.view["azimuth"]); el = math.radians(self.view["elevation"])
            right = (-math.sin(az), math.cos(az), 0)
            up = (-math.cos(az) * math.sin(el), -math.sin(az) * math.sin(el), math.cos(el))
            scale = self.view["zoom"] * 3 / max(100, min(self.canvas.winfo_width(), self.canvas.winfo_height()))
            self.view["centre"] = [value + scale * (-dx * r + dy * u)
                                   for value, r, u in zip(self.view["centre"], right, up)]
        self.schedule_render()

    def _release(self, event):
        self._drag = None

    def _wheel(self, event):
        if event.delta:
            self._zoom(0.85 if event.delta > 0 else 1 / 0.85)

    def _zoom(self, factor):
        if self.ready:
            self.view["zoom"] = max(0.005, min(200, self.view["zoom"] * factor))
            self.schedule_render()

    def destroy(self):
        if self.closed:
            return
        self.closed = True
        for timer in (self._render_timer, self._poll_timer):
            if timer is not None:
                self.after_cancel(timer)
        if self.process is not None and self.process.pid is not None:
            if self.process.is_alive():
                self.process.terminate()
            self.process.join(timeout=0.5)
            if self.process.is_alive():
                self.process.kill()
                self.process.join(timeout=0.5)
            self.process.close()
        for channel in (self.commands, self.events):
            if channel is not None:
                channel.cancel_join_thread()
                channel.close()
        self._image = None
        super().destroy()
