"""Local の実 HTTP 要求と応答を観測する。必要時だけ実項目の接頭辞でページを分ける。"""
import base64
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import urllib.error
import urllib.request

PAGE_BYTES = 1024 * 1024


def item_bytes(item):
    size = 0
    for name, attribute in item.items():
        size += len(name.encode("utf-8"))
        kind, value = next(iter(attribute.items()))
        if kind == "S":
            size += len(value.encode("utf-8"))
        elif kind == "N":
            # 受入済み JVM fixture と同じ、有効桁数による見積もり。
            size += (len(Decimal(value).normalize().as_tuple().digits) + 1) // 2 + 1
        elif kind == "B":
            size += len(base64.b64decode(value))
        else:
            raise ValueError(f"unexpected journal attribute: {kind}")
    return size


class QueryObserver:
    def __init__(self, upstream, journal, output):
        self.upstream = upstream
        self.journal = journal
        self.output = Path(output)
        self.records = []
        self.context = {}
        self.correct_oversized_pages = False
        self.lock = threading.Lock()
        observer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                headers = {key: value for key, value in self.headers.items()
                           if key.lower() not in ("host", "content-length", "connection")}
                request = urllib.request.Request(observer.upstream, data=body, headers=headers, method="POST")
                try:
                    response = urllib.request.urlopen(request, timeout=60)
                except urllib.error.HTTPError as error:
                    response = error
                with response:
                    raw = response.read()
                    status = response.status
                    content_type = response.headers.get("Content-Type", "application/x-amz-json-1.0")
                outgoing = raw
                operation = self.headers.get("X-Amz-Target", "").split(".")[-1]
                if operation == "Query" and status == 200:
                    sent, received = json.loads(body), json.loads(raw)
                    if sent.get("TableName") == observer.journal:
                        items = received.get("Items", [])
                        sizes = [item_bytes(item) for item in items]
                        effective = received
                        corrected = False
                        if observer.correct_oversized_pages and sum(sizes) > PAGE_BYTES:
                            used, count = 0, 0
                            for size in sizes:
                                if used + size > PAGE_BYTES:
                                    break
                                used += size
                                count += 1
                            if count == 0:
                                raise ValueError("no real item fits in one page")
                            last = items[count - 1]
                            effective = dict(received, Items=items[:count], Count=count, ScannedCount=count,
                                             LastEvaluatedKey={"aid": last["aid"], "seq_nr": last["seq_nr"]})
                            outgoing = json.dumps(effective, separators=(",", ":")).encode()
                            corrected = True
                        row = {"context": dict(observer.context), "request": sent, "raw_response": received,
                               "effective_response": effective, "actual_item_bytes": sizes,
                               "raw_bytes": sum(sizes), "corrected_from_actual_prefix": corrected}
                        with observer.lock:
                            observer.records.append(row)
                            with observer.output.open("a") as stream:
                                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(outgoing)))
                self.end_headers()
                self.wfile.write(outgoing)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.endpoint = f"http://127.0.0.1:{self.server.server_port}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=10)
