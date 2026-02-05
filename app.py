from flask import Flask, request, jsonify
from docling.document_converter import DocumentConverter
from pathlib import Path

app = Flask(__name__)

port = 5952

# Create converter instance
converter = DocumentConverter()


@app.route("/", methods=["GET"])
def home():
    return jsonify({"Server": "Running", "Port": port, "Message": "Simple Local Rest API to process PDF files"})

def get_pdf_path(data):
    if not data or "path" not in data:
        return None, jsonify({"error": "Missing 'path' in request body"}), 400
    path = Path(data["path"])


    if not path.exists():
        return None, jsonify({"error": f"File not found: {path}"}), 404

    if path.suffix.lower() != ".pdf":
        return None, jsonify({"error": "Only PDF files are supported"}), 400

    return path, None, None

@app.route("/export_to_markdown", methods=["POST"])
def post_export_to_markdown():
        data = request.get_json()
        path, error, status = get_pdf_path(data)
        if error:
            return error, status
        result = converter.convert(path)
        markdown = result.document.export_to_markdown()
        return jsonify({
            "path": str(path),
            "format": "markdown",
            "content": markdown,
            "status": "success"
        })

@app.route("/export_to_json", methods=["POST"])
def post_export_to_json():
    data = request.get_json()
    path, error, status = get_pdf_path(data)
    if error:
        return error, status

    result = converter.convert(path)
    json_data = result.document.export_to_dict()

    return jsonify({
        "path": str(path),
        "format": "json",
        "content": json_data,
        "status": "success"
    })

@app.route("/export_to_doctags", methods=["POST"])
def post_export_to_doctags():
    data = request.get_json()
    path, error, status = get_pdf_path(data)
    if error:
        return error, status
    result = converter.convert(path)
    doctags = result.document.export_to_doctags()
    return jsonify({
        "path": str(path),
        "format": "doctags",
        "content": doctags,
        "status": "success"
    })

@app.route("/export_to_text", methods=["POST"])
def post_export_to_text():
    data = request.get_json()
    path, error, status = get_pdf_path(data)
    if error:
        return error, status
    result = converter.convert(path)
    text = result.document.export_to_text()
    return jsonify({
        "path": str(path),
        "format": "text",
        "content": text,
        "status": "success"
    })

if __name__ == "__main__":
    app.run(host="127.0.0.1",debug=False, port=port)
