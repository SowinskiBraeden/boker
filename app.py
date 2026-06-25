#!/usr/bin/env python3
from boker import create_app

app = create_app()

if __name__ == "__main__":
    import os
    app.run(debug=os.getenv("FLASK_DEBUG", "0") == "1")
