#!/usr/bin/env python3
"""Independent AI/V2V pre-annotation and atomic ground-truth commit service."""
from __future__ import annotations

import argparse, base64, csv, json, math, os, shutil, subprocess, tempfile, time
from collections import defaultdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

OK, ERROR = "OK", "ERROR"
ROOT = Path(os.getenv("EXTERNAL_DATA_ROOT", "/home/user/cjg/conch_data")).resolve()
WORK_ROOT = Path(os.getenv("PREANNOTATION_WORK_ROOT", "/home/user/cjg/preannotation_jobs")).resolve()
MYSQL_CONTAINER = os.getenv("MYSQL_DOCKER_CONTAINER", "hb-wblabel-mysql-1")
MYSQL_USER = os.getenv("XTREME1_MYSQL_USER", "xtreme1")
MYSQL_PASSWORD = os.getenv("XTREME1_MYSQL_PASSWORD", "Rc4K3L6f")
MYSQL_DATABASE = os.getenv("XTREME1_MYSQL_DATABASE", "xtreme1")
MAX_V2V_GAP_NS = int(os.getenv("PREANNOTATION_V2V_MAX_GAP_NS", "500000000"))


def mysql_rows(sql: str) -> list[list[str]]:
    cmd = ["docker", "exec", MYSQL_CONTAINER, "mysql", f"-u{MYSQL_USER}", f"-p{MYSQL_PASSWORD}",
           "--batch", "--raw", "--skip-column-names", MYSQL_DATABASE, "-e", sql]
    result = subprocess.run(cmd, text=True, capture_output=True, timeout=120)
    if result.returncode: raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return [line.split("\t") for line in result.stdout.splitlines() if line.strip()]


def sql_ids(values: list[int]) -> str:
    return ",".join(str(int(v)) for v in values) or "NULL"


def flatten(nodes: list[dict[str, Any]], parent: str = ""):
    for node in nodes or []:
        name = str(node.get("name") or "")
        here = f"{parent}/{name}".strip("/")
        if node.get("fileId") is not None:
            yield {**node, "dirName": parent, "treePath": here}
        yield from flatten(node.get("files") or [], here)


def load_frames(data_ids: list[int]) -> dict[int, dict[str, Any]]:
    rows = mysql_rows("SELECT id,name,parent_id,content FROM data WHERE type='SINGLE_DATA' AND is_deleted=0 "
                      f"AND id IN ({sql_ids(data_ids)})")
    frames, file_ids = {}, set()
    for row in rows:
        nodes = json.loads(row[3] or "[]")
        files = list(flatten(nodes))
        file_ids.update(int(f["fileId"]) for f in files)
        frames[int(row[0])] = {"id": int(row[0]), "name": row[1], "parentId": int(row[2]), "files": files}
    paths = {}
    if file_ids:
        for row in mysql_rows(f"SELECT id,name,path FROM file WHERE id IN ({sql_ids(list(file_ids))})"):
            paths[int(row[0])] = {"name": row[1], "path": row[2]}
    for frame in frames.values():
        for item in frame["files"]: item.update(paths.get(int(item["fileId"]), {}))
    return frames


def safe_path(raw: str) -> Path:
    path = Path(raw)
    resolved = (path if path.is_absolute() else ROOT / path).resolve()
    if resolved != ROOT and ROOT not in resolved.parents: raise ValueError(f"Path escapes external root: {raw}")
    return resolved


def artifact_path(url: str) -> Path | None:
    raw = urlparse(str(url)).path.replace("\\", "/")
    marker = "/external-data/"
    if marker not in raw: return None
    try: return safe_path(raw.split(marker, 1)[1])
    except ValueError: return None


def resource(frame: dict[str, Any], pattern: str, suffix: str = "") -> dict[str, Any] | None:
    pattern = pattern.lower()
    for item in frame["files"]:
        haystack = (str(item.get("dirName")) + "/" + str(item.get("name"))).lower()
        if pattern in haystack and (not suffix or str(item.get("name", "")).lower().endswith(suffix)): return item
    return None


def point_item(frame):
    return resource(frame, "point_cloud", ".bin") or resource(frame, "point_cloud", ".pcd")


def clip_root_from_point(path: Path) -> Path:
    for parent in path.parents:
        if parent.name == "lidars": return parent.parent
    raise ValueError(f"Cannot infer clip root from point cloud: {path}")


def model_datas(frames: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for frame in frames.values():
        point = point_item(frame)
        if not point: continue
        images = ["/external-data/" + str(x["path"]).replace("\\", "/").lstrip("/")
                  for x in frame["files"] if "image" in str(x.get("dirName", "")).lower()]
        result.append({"id": frame["id"], "pointCloudUrl": "/external-data/" + str(point["path"]).replace("\\", "/").lstrip("/"), "imageUrls": images})
    return result


def call_ai(model_url: str, frames: dict[int, dict[str, Any]]) -> tuple[dict[str, list[dict]], dict[str, dict]]:
    if not model_url: raise ValueError("Selected model has no inference URL")
    model_url = model_url.replace("host.docker.internal", "127.0.0.1")
    if not urlparse(model_url).path: model_url = model_url.rstrip("/") + "/infer"
    body = json.dumps({"datas": model_datas(frames)}).encode()
    with urlopen(Request(model_url, data=body, headers={"Content-Type": "application/json"}), timeout=6*60*60) as response:
        payload = json.loads(response.read())
    if str(payload.get("code", OK)).upper() != OK: raise RuntimeError(payload.get("message") or "AI inference failed")
    predictions, occ = {}, {}
    for item in payload.get("data") or []:
        data_id = str(item.get("id")); predictions[data_id] = []
        for index, obj in enumerate(item.get("objects") or []):
            predictions[data_id].append({**obj, "id": f"AI-{data_id}-{index}", "source": "AI"})
        try: outputs = json.loads(item.get("message") or "{}").get("outputs") or {}
        except json.JSONDecodeError: outputs = {}
        artifact = {k + "Url": v for k, v in outputs.items() if k in {"occ", "label", "npz"}}
        if artifact: occ[data_id] = artifact
    return predictions, occ


def timestamp_of(name: str) -> int:
    digits = "".join(ch if ch.isdigit() else " " for ch in name).split()
    return int(next((v for v in digits if len(v) >= 16), "0"))


def box_from_v2v(row: dict[str, str], data_id: int, index: int) -> dict[str, Any] | None:
    try:
        pts = [(float(row[f"point{i}_x_m"]), float(row[f"point{i}_y_m"]), float(row[f"point{i}_z_m"])) for i in range(1, 9)]
        height = float(row.get("height_m") or (max(p[2] for p in pts)-min(p[2] for p in pts)))
        center = [float(row["center_x_m"]), float(row["center_y_m"]), float(row["center_z_m"])]
        length = float(row["length_m"])
        width = float(row["width_m"])
        heading = float(row["heading_rad"])
    except (ValueError, KeyError): return None
    center[2] += height / 2.0
    return {"id": f"V2V-{data_id}-{index}", "label": row.get("truck_type") or "Truck", "confidence": 1.0,
            "x": center[0], "y": center[1], "z": center[2], "dx": length, "dy": width, "dz": height,
            "rotX": 0.0, "rotY": 0.0, "rotZ": heading, "source": "V2V",
            "vehicleId": row.get("vehicle_id"), "v2vTimestampNs": int(row.get("frame_timestamp_ns") or row.get("box_timestamp_ns") or 0)}


def load_v2v(frames: dict[int, dict[str, Any]]) -> dict[str, list[dict]]:
    csv_cache, result = {}, {}
    for frame in frames.values():
        item = resource(frame, "v2v", ".csv")
        if not item: result[str(frame["id"])] = []; continue
        path = safe_path(item["path"])
        if path not in csv_cache:
            with path.open(encoding="utf-8-sig", newline="") as stream: csv_cache[path] = list(csv.DictReader(stream))
        ts = timestamp_of(frame["name"])
        grouped = defaultdict(list)
        for row in csv_cache[path]:
            try: grouped[int(row.get("frame_timestamp_ns") or row.get("box_timestamp_ns") or 0)].append(row)
            except ValueError: pass
        if not grouped: result[str(frame["id"])] = []; continue
        nearest = min(grouped, key=lambda value: abs(value-ts)) if ts else min(grouped)
        if ts and abs(nearest-ts) > MAX_V2V_GAP_NS: result[str(frame["id"])] = []; continue
        result[str(frame["id"])] = [box for i,row in enumerate(grouped[nearest]) if (box := box_from_v2v(row, frame["id"], i))]
    return result


def rect(box):
    cx,cy,dx,dy,yaw = (float(box.get(k,0)) for k in ("x","y","dx","dy","rotZ"))
    c,s=math.cos(yaw),math.sin(yaw)
    return [(cx+x*c-y*s,cy+x*s+y*c) for x,y in [(-dx/2,-dy/2),(dx/2,-dy/2),(dx/2,dy/2),(-dx/2,dy/2)]]


def polygon_area(poly): return abs(sum(poly[i][0]*poly[(i+1)%len(poly)][1]-poly[(i+1)%len(poly)][0]*poly[i][1] for i in range(len(poly)))/2) if len(poly)>2 else 0
def intersect_poly(subject, clip):
    orientation = 1 if sum(clip[i][0]*clip[(i+1)%4][1]-clip[(i+1)%4][0]*clip[i][1] for i in range(4)) >= 0 else -1
    for i in range(4):
        a,b=clip[i],clip[(i+1)%4]; output=[]
        inside=lambda p: orientation*((b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0])) >= -1e-9
        def hit(p,q):
            dx1,dy1=q[0]-p[0],q[1]-p[1]; dx2,dy2=b[0]-a[0],b[1]-a[1]
            den=dx1*dy2-dy1*dx2
            t=((a[0]-p[0])*dy2-(a[1]-p[1])*dx2)/den if abs(den)>1e-12 else 0
            return (p[0]+t*(q[0]-p[0]),p[1]+t*(q[1]-p[1]))
        for j,p in enumerate(subject):
            q=subject[j-1]
            if inside(p):
                if not inside(q): output.append(hit(q,p))
                output.append(p)
            elif inside(q): output.append(hit(q,p))
        subject=output
        if not subject: break
    return subject


def iou(a,b):
    pa,pb=rect(a),rect(b); inter=polygon_area(intersect_poly(pa,pb)); union=polygon_area(pa)+polygon_area(pb)-inter
    return inter/union if union>0 else 0


def fuse(ai: dict[str,list[dict]], v2v: dict[str,list[dict]], threshold: float):
    result={}
    for key in set(ai)|set(v2v):
        left=[dict(x) for x in ai.get(key,[])]; right=v2v.get(key,[]); used=set(); merged=[]
        for pred in left:
            match=max(((iou(pred,v),i,v) for i,v in enumerate(right) if i not in used), default=(0,-1,None), key=lambda x:x[0])
            if match[0] > threshold:
                used.add(match[1]); replacement=dict(match[2]); replacement["aiLabel"]=pred.get("label"); replacement["matchIou"]=match[0]; merged.append(replacement)
            else: merged.append(pred)
        merged.extend(v for i,v in enumerate(right) if i not in used)
        result[key]=merged
    return result


def atomic_write(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists(): shutil.copy2(path, path.with_name(path.name + ".bak." + time.strftime("%Y%m%d%H%M%S")))
    fd,tmp=tempfile.mkstemp(prefix=path.name+".",suffix=".tmp",dir=path.parent)
    try:
        with os.fdopen(fd,"wb") as stream: stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def attrs_to_annotation(obj):
    contour=obj.get("contour") or {}; center=contour.get("center3D") or {}; size=contour.get("size3D") or {}; rot=contour.get("rotation3D") or {}
    yaw=float(rot.get("z",0)); label=obj.get("modelClass") or obj.get("classType") or (obj.get("meta") or {}).get("classType") or "unknown"
    return {"translation":[float(center.get("x",0)),float(center.get("y",0)),float(center.get("z",0))],
            "size":[float(size.get("x",0)),float(size.get("y",0)),float(size.get("z",0))],
            "rotation":[math.cos(yaw/2),0.0,0.0,math.sin(yaw/2)],"category":label,"sub_category":"",
            "velocity":[0.0,0.0,0.0],"num_lidar_pts":max(1,int(contour.get("pointN") or 1)),"num_radar_pts":0}


def commit(payload):
    ids=[int(x) for x in payload.get("dataIds") or []]; frames=load_frames(ids)
    gt=defaultdict(list)
    for data_id,attrs in mysql_rows("SELECT data_id,class_attributes FROM data_annotation_object "
                                    f"WHERE source_id=-1 AND data_id IN ({sql_ids(ids)})"):
        gt[int(data_id)].append(attrs_to_annotation(json.loads(attrs)))
    obstacle_groups=defaultdict(list); occ_written=0
    occ_labels=payload.get("occLabels") or {}
    draft_path = WORK_ROOT / f"job_{int(payload['preAnnotationId'])}" / "draft.json"
    draft = json.loads(draft_path.read_text(encoding="utf-8")) if draft_path.exists() else {}
    occ_artifacts = draft.get("occArtifacts") or {}
    for data_id,frame in frames.items():
        point=point_item(frame)
        if not point: continue
        point_path=safe_path(point["path"]); clip=clip_root_from_point(point_path)
        obstacle=resource(frame,"obstacle_3d.json")
        obstacle_path=safe_path(obstacle["path"]) if obstacle else clip/"anno"/"obstacle_3d.json"
        obstacle_groups[obstacle_path].append((frame,gt.get(data_id,[]),point_path))
        encoded=occ_labels.get(str(data_id)); labels = base64.b64decode(encoded) if encoded else None
        if labels is None:
            source = artifact_path((occ_artifacts.get(str(data_id)) or {}).get("labelUrl", ""))
            if source and source.exists(): labels = source.read_bytes()
        if labels:
            size=point_path.stat().st_size
            if not labels or size % (len(labels)*4) or not (1 <= size//(len(labels)*4) <= 16):
                raise ValueError(f"OCC label length does not match point cloud for dataId={data_id}")
            original=resource(frame,"occ_label",".label")
            target=safe_path(original["path"]) if original else clip/"anno"/"occ_labels"/"LIDAR_CAR"/(point_path.stem+".label")
            atomic_write(target,labels); occ_written+=1
    for path,items in obstacle_groups.items():
        doc=json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        for frame,annotations,point_path in items:
            key=point_path.stem
            entry=doc.get(key) if isinstance(doc.get(key),dict) else {"FrameID":key,"channel":"LIDAR_CAR","filepath":str(point_path.relative_to(clip)),"timestamp":int(key) if key.isdigit() else 0}
            entry["annotations"]=annotations; doc[key]=entry
            if "first_frame" not in doc: doc["first_frame"]=key
        atomic_write(path,(json.dumps(doc,ensure_ascii=False,indent=2)+"\n").encode("utf-8"))
    return {"clips":len(obstacle_groups),"frames":len(frames),"occLabels":occ_written}


def preannotate(payload):
    job=int(payload["preAnnotationId"]); ids=[int(x) for x in payload.get("dataIds") or []]; mode=str(payload.get("sourceMode") or "AI").upper()
    frames=load_frames(ids); ai,occ,v2v={},{},{}
    if mode in {"AI","HYBRID"}: ai,occ=call_ai(str(payload.get("modelUrl") or ""),frames)
    if mode in {"V2V","HYBRID"}: v2v=load_v2v(frames)
    predictions=ai if mode=="AI" else v2v if mode=="V2V" else fuse(ai,v2v,float(payload.get("iouThreshold") or .5))
    work=WORK_ROOT/f"job_{job}"; work.mkdir(parents=True,exist_ok=True); output=work/"draft.json"
    atomic_write(output,json.dumps({"predictions":predictions,"occArtifacts":occ},ensure_ascii=False,indent=2).encode())
    return {"predictions":predictions,"occArtifacts":occ,"outputPath":str(output),"logPath":str(work/"preannotation.log")}


def respond(handler,status,body):
    raw=json.dumps(body,ensure_ascii=False).encode(); handler.send_response(status); handler.send_header("Content-Type","application/json; charset=utf-8"); handler.send_header("Content-Length",str(len(raw))); handler.end_headers(); handler.wfile.write(raw)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self): respond(self,HTTPStatus.OK,{"code":OK,"message":"ok"}) if self.path=="/health" else respond(self,HTTPStatus.NOT_FOUND,{"code":ERROR,"message":"not found"})
    def do_POST(self):
        try:
            payload=json.loads(self.rfile.read(int(self.headers.get("Content-Length","0"))) or b"{}")
            data=preannotate(payload) if self.path.rstrip("/")=="/preannotate" else commit(payload) if self.path.rstrip("/")=="/commit" else None
            if data is None: respond(self,HTTPStatus.NOT_FOUND,{"code":ERROR,"message":"not found"})
            else: respond(self,HTTPStatus.OK,{"code":OK,"message":"","data":data})
        except Exception as exc: respond(self,HTTPStatus.OK,{"code":ERROR,"message":str(exc),"data":None})
    def log_message(self,fmt,*args): pass


def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--host",default="0.0.0.0"); parser.add_argument("--port",type=int,default=8520); args=parser.parse_args()
    WORK_ROOT.mkdir(parents=True,exist_ok=True); print(f"Pre-annotation service listening on {args.host}:{args.port}",flush=True); HTTPServer((args.host,args.port),Handler).serve_forever()


if __name__=="__main__": main()
