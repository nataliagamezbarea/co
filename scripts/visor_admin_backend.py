#!/usr/bin/env python3
"""Worker de compilación de apuntes LaTeX para GitHub Actions."""
import argparse
import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

def gh_api(repo, path, method="GET", data=None, token=None):
    if not token:
        token = os.environ.get("GH_TOKEN_GENERAL") or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    url = f"https://api.github.com/repos/{repo}/{path}"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "LaTeX-Apuntes-Worker"
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req_body = None
    if data is not None:
        req_body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=req_body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            content = resp.read()
            if resp.status == 204:
                return {"ok": True, "status": 204}
            return json.loads(content.decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        return {"ok": False, "status": e.code, "error": err_body}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def compilar_un_apunte(grado, archivo, nombre_apunte, repo_general, payload=None):
    token = os.environ.get("GH_TOKEN_GENERAL") or os.environ.get("GH_TOKEN")
    if not repo_general or not grado or not archivo:
        return False, json.dumps({
            "ok": False,
            "total": 1,
            "compilados": 0,
            "exitosos": [],
            "fallidos": [{"nombre": nombre_apunte or "Apunte", "grado": grado, "archivo": archivo, "error": "Faltan parámetros grado/archivo/repo_general"}]
        }, ensure_ascii=False)

    nombre_limpio = nombre_apunte or Path(archivo).stem
    dest_path = f"apuntes/{nombre_limpio}.pdf"

    # 1. Obtener archivo original desde repo_general
    res = gh_api(repo_general, f"contents/{archivo}?ref={grado}", token=token)
    pdf_bytes = None
    if isinstance(res, dict) and "content" in res:
        pdf_bytes = base64.b64decode(res["content"])
    else:
        res_arch = gh_api(repo_general, f"contents/archivos/{archivo}?ref={grado}", token=token)
        if isinstance(res_arch, dict) and "content" in res_arch:
            pdf_bytes = base64.b64decode(res_arch["content"])

    if not pdf_bytes:
        return False, json.dumps({
            "ok": False,
            "total": 1,
            "compilados": 0,
            "exitosos": [],
            "fallidos": [{"nombre": nombre_limpio, "grado": grado, "archivo": archivo, "error": f"No se pudo descargar {archivo} desde {repo_general}"}]
        }, ensure_ascii=False)

    # 2. Subir PDF a apuntes/{nombre_limpio}.pdf en la rama del grado
    put_data = {
        "message": f"Compilado apunte {nombre_limpio} (LaTeX Worker)",
        "content": base64.b64encode(pdf_bytes).decode("utf-8"),
        "branch": grado
    }
    check_exist = gh_api(repo_general, f"contents/{dest_path}?ref={grado}", token=token)
    if isinstance(check_exist, dict) and "sha" in check_exist:
        put_data["sha"] = check_exist["sha"]

    put_res = gh_api(repo_general, f"contents/{dest_path}", method="PUT", data=put_data, token=token)
    if not put_res or ("content" not in put_res and put_res.get("status") not in (200, 201)):
        return False, json.dumps({
            "ok": False,
            "total": 1,
            "compilados": 0,
            "exitosos": [],
            "fallidos": [{"nombre": nombre_limpio, "grado": grado, "archivo": archivo, "error": f"Error al guardar en GitHub: {put_res}"}]
        }, ensure_ascii=False)

    # 3. Actualizar revision.json en master
    try:
        rev_res = gh_api(repo_general, "contents/almacen/datos/revision.json?ref=master", token=token)
        rev = {}
        rev_sha = None
        if isinstance(rev_res, dict) and "content" in rev_res:
            rev_sha = rev_res.get("sha")
            rev = json.loads(base64.b64decode(rev_res["content"]).decode("utf-8"))

        k = f"{grado}::{archivo}"
        rev[k] = rev.get(k, {})
        rev[k]["inc_apunte"] = True
        rev[k]["nombre_apunte"] = nombre_limpio
        rev[k]["latex_compilado"] = True

        rev_put_data = {
            "message": f"Actualizar revision.json para apunte {nombre_limpio}",
            "content": base64.b64encode(json.dumps(rev, indent=2, ensure_ascii=False).encode("utf-8")).decode("utf-8"),
            "branch": "master"
        }
        if rev_sha:
            rev_put_data["sha"] = rev_sha
        gh_api(repo_general, "contents/almacen/datos/revision.json", method="PUT", data=rev_put_data, token=token)
    except Exception as e:
        print(f"Advertencia revision.json: {e}")

    return True, json.dumps({
        "ok": True,
        "total": 1,
        "compilados": 1,
        "exitosos": [{"nombre": nombre_limpio, "grado": grado, "archivo": archivo, "ruta": dest_path}],
        "fallidos": []
    }, ensure_ascii=False)

def compilar_todos(grado, repo_general, payload=None):
    token = os.environ.get("GH_TOKEN_GENERAL") or os.environ.get("GH_TOKEN")
    if not repo_general:
        return False, json.dumps({"ok": False, "total": 0, "compilados": 0, "exitosos": [], "fallidos": [{"nombre": "Todos", "error": "Falta repo_general"}]})

    rev_res = gh_api(repo_general, "contents/almacen/datos/revision.json?ref=master", token=token)
    rev = {}
    if isinstance(rev_res, dict) and "content" in rev_res:
        rev = json.loads(base64.b64decode(rev_res["content"]).decode("utf-8"))

    exitosos = []
    fallidos = []

    for k, v in rev.items():
        if not v or not v.get("inc_apunte"):
            continue
        parts = k.split("::")
        if len(parts) < 2:
            continue
        item_grado, item_archivo = parts[0], parts[1]
        if grado and grado != "__TODAS__" and item_grado != grado:
            continue

        item_nombre = v.get("nombre_apunte") or Path(item_archivo).stem
        ok_item, res_str = compilar_un_apunte(item_grado, item_archivo, item_nombre, repo_general)
        if ok_item:
            exitosos.append({"nombre": item_nombre, "grado": item_grado, "archivo": item_archivo, "ruta": f"apuntes/{item_nombre}.pdf"})
        else:
            fallidos.append({"nombre": item_nombre, "grado": item_grado, "archivo": item_archivo, "error": "Fallo al procesar"})

    total = len(exitosos) + len(fallidos)
    return len(fallidos) == 0, json.dumps({
        "ok": len(fallidos) == 0,
        "total": total,
        "compilados": len(exitosos),
        "exitosos": exitosos,
        "fallidos": fallidos
    }, ensure_ascii=False)

def run(a):
    if a.accion == "compile_apunte":
        return compilar_un_apunte(a.grado, a.archivo, a.nombre_apunte, a.repo_general, a.payload)
    if a.accion == "compile_all_apuntes":
        return compilar_todos(a.grado, a.repo_general, a.payload)
    return False, json.dumps({"ok": False, "error": f"Acción no soportada: {a.accion}"})

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--accion", required=True)
    p.add_argument("--grado", default="")
    p.add_argument("--archivo", default="")
    p.add_argument("--nombre-apunte", default="")
    p.add_argument("--repo-general", default="")
    p.add_argument("--payload", default="{}")
    a = p.parse_args()

    try:
        a.payload = json.loads(a.payload)
    except Exception:
        a.payload = {}

    ok, msg = run(a)
    print(msg)
    return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(main())
