import os
from bridge.config import load_config
from bridge.server import make_server


def main():
    os.umask(0o077)  # requests.db and logs hold private questions
    port = int(load_config()["port"])
    server = make_server(port)
    print(f"bridge on http://127.0.0.1:{server.server_address[1]}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
