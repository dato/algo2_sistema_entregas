from main import app


if __name__ == "__main__":
    app.config["PROPAGATE_EXCEPTIONS"] = True
    app.run()
