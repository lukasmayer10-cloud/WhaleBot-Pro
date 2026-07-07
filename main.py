from app.web.server import create_app

app = create_app()

if __name__ == "__main__":
    print("WhaleBot Pro X 6.1 POSITION MANAGER läuft auf http://127.0.0.1:8080")
    app.run(host="127.0.0.1", port=8080, threaded=True)
