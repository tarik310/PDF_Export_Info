from flask import Flask, request, jsonify

app = Flask(__name__)


@app.route("/", methods=["GET"])
def home():
    return jsonify({"message": "Simple Local Rest API to process PDF files"})



@app.route("/export_to_markdown", methods=["POST"])
def create_item():
    data = request.get_json()
    item = {
        "id": 1,
        "name": data.get("name"),
        "description": data.get("description")
    }
    return jsonify(item), 201




if __name__ == "__main__":
    app.run(debug=True)
