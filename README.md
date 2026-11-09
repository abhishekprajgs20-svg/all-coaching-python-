# PDF → TXT Studio — Vercel edition

A browser UI with a Python serverless backend. The PDF parsing functions are carried over from the supplied desktop script; the Tkinter window is replaced by a web interface.

## Deploy to Vercel

1. Create a new GitHub repository and upload the **contents** of this folder (not the outer folder itself).
2. In Vercel, choose **Add New → Project**, import that GitHub repository, and deploy.
3. Framework preset: **Other**. Build command: leave blank. Output directory: `public`. Install command: `pip install -r requirements.txt` (if the dashboard asks for one; Vercel's Python runtime installs `requirements.txt` for the function).
4. No environment variables are required.
5. After deployment, open the Vercel URL. The `/api/health` endpoint should return `{"ok":true,...}`.

`vercel.json` routes `/api/*` to the FastAPI application in `api/index.py`. `api/parser_engine.py` contains the original extraction logic without its Tkinter GUI.

## Supported modes

- **SFG / Sarthi IAS:** upload combined question + answer + explanation PDFs.
- **Next IAS / PW / Vision IAS / Vajiram:** upload test PDFs and matching solution PDFs. The parser pairs files using normalized filenames, with positional pairing as a fallback when the number of test and solution files is equal.

## Important Vercel serverless limits

- The UI and API enforce a **4 MB combined upload limit** to stay below Vercel's standard serverless request-body ceiling. This is a hard deployment constraint; large PDF batches should be split into smaller runs.
- Serverless execution time and memory are finite. Very large or complex PDFs may time out; split them into smaller batches.
- The parser uses PyMuPDF text extraction. Scanned/image-only PDFs are not OCR'd, so they may produce little or no text.
- The generated validation report flags suspicious extraction; it does not certify correctness. Review warnings and verify answer/explanation alignment manually.

## Local smoke test

```bash
python -m pip install -r requirements.txt
uvicorn api.index:app --reload
```

Then visit `http://127.0.0.1:8000` (for local testing, serve `public/index.html` separately or use Vercel CLI). API health: `http://127.0.0.1:8000/api/health`.
