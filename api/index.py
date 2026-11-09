from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from typing import List, Optional
from pathlib import Path
import tempfile, zipfile, io, os, re, shutil
from parser_engine import process_coaching

app = FastAPI(title="Coaching PDF to TXT", docs_url=None, redoc_url=None)
COACHES = {"SFG", "Sarthi IAS", "Next IAS", "PW", "Vision IAS", "Vajiram"}
MAX_TOTAL_BYTES = 4 * 1024 * 1024  # stay below Vercel's standard request-body ceiling

@app.get("/api/health")
async def health():
    return {"ok": True, "service": "Coaching PDF → TXT", "engine": "PyMuPDF"}

@app.post("/api/process")
async def process(
    coach: str = Form(...),
    test_files: List[UploadFile] = File(...),
    solution_files: Optional[List[UploadFile]] = File(None),
):
    if coach not in COACHES:
        raise HTTPException(400, "Please select a valid coaching format.")
    if not test_files:
        raise HTTPException(400, "Upload at least one test PDF.")
    single = coach in ("SFG", "Sarthi IAS")
    if not single and not solution_files:
        raise HTTPException(400, "This coaching format requires separate solution PDF(s).")

    all_files = list(test_files) + ([] if single else list(solution_files or []))
    total = 0
    for f in all_files:
        if not f.filename or not f.filename.lower().endswith(".pdf"):
            raise HTTPException(400, "Only PDF files are supported.")
        # Read once and cache bytes; this also makes size validation deterministic.
        f._cached_bytes = await f.read()
        total += len(f._cached_bytes)
        if total > MAX_TOTAL_BYTES:
            raise HTTPException(413, "Combined upload is larger than 4 MB. Vercel serverless requests have a strict payload limit; upload fewer/smaller PDFs at a time.")
        if not f._cached_bytes.startswith(b"%PDF"):
            raise HTTPException(400, f"{f.filename} does not look like a valid PDF.")

    workdir = tempfile.mkdtemp(prefix="coachpdf_")
    try:
        test_paths, sol_paths = [], []
        def save_upload(upload, folder, index):
            safe = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(upload.filename).name).strip("._") or f"file_{index}.pdf"
            # Prefix duplicate names to prevent overwrites.
            dest = Path(folder) / f"{index:03d}_{safe}"
            dest.write_bytes(upload._cached_bytes)
            return str(dest)
        test_dir = Path(workdir) / "tests"; sol_dir = Path(workdir) / "solutions"
        test_dir.mkdir(); sol_dir.mkdir()
        for i, f in enumerate(test_files, 1): test_paths.append(save_upload(f, test_dir, i))
        if not single:
            for i, f in enumerate(solution_files or [], 1): sol_paths.append(save_upload(f, sol_dir, i))

        outputs, reports = process_coaching(coach, test_paths, sol_paths)
        report_path = test_dir / "coaching_txt_validation_report.txt"
        # process_coaching writes the report beside the first test PDF.
        if not report_path.exists():
            report_path.write_text("COACHING PDF → TXT VALIDATION REPORT\n\n" + "\n".join(reports), encoding="utf-8")

        if not outputs:
            detail = "\n".join(reports) or "No output was generated."
            raise HTTPException(422, detail[:5000])

        memory = io.BytesIO()
        with zipfile.ZipFile(memory, "w", zipfile.ZIP_DEFLATED) as zf:
            for out in outputs:
                if os.path.exists(out): zf.write(out, arcname=Path(out).name)
            if report_path.exists(): zf.write(report_path, arcname="coaching_txt_validation_report.txt")
            zf.writestr("processing_summary.txt", "COACHING: " + coach + "\n\n" + "\n".join(reports) + "\n")
        memory.seek(0)
        filename = "coaching_formatted_output.zip"
        headers = {"Content-Disposition": f'attachment; filename="{filename}"', "X-Processed-Files": str(len(outputs))}
        return StreamingResponse(memory, media_type="application/zip", headers=headers)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"Processing failed: {type(exc).__name__}: {str(exc)[:700]}")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
