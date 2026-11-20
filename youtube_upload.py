#!/usr/bin/env python3
"""LoopFrenzy Control Room: YouTube upload script (complete and working; this is the upload path the tool uses).

    python3 youtube_upload.py connect                         # one-time Google sign-in (OAuth 2.0, Desktop app)
    python3 youtube_upload.py upload short.mp4 "Title" "Description" "#tag1 #tag2"
    python3 youtube_upload.py status VIDEO_ID                 # confirm the upload is processed and public

Uploads ONE video, which the channel owner edited and approved, to the owner's OWN channel. It uses the
resumable upload protocol of the YouTube Data API v3 (videos.insert), then confirms the result with
videos.list. Standard library only. It needs `google_client.json` (the OAuth Desktop client file
downloaded from Google Cloud) next to this script. Tokens are saved in `google_token.json`, readable only
by the owner (mode 600). Revoke access at https://myaccount.google.com/permissions
"""
import http.server, json, os, sys, threading, time, urllib.parse, urllib.request, webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
CLIENT = os.path.join(HERE, "google_client.json")
TOKEN = os.path.join(HERE, "google_token.json")
SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"
PORT = 8766
REDIRECT = f"http://127.0.0.1:{PORT}/callback"


def client():
    d = json.load(open(CLIENT))
    return d.get("installed") or d["web"]


def post_form(url, data):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode())
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def api_get(url, token):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def connect():
    """OAuth 2.0 for installed apps: open the consent screen, catch the code on a loopback port, store tokens."""
    got = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            got.update(q)
            self.send_response(200); self.send_header("Content-Type", "text/plain"); self.end_headers()
            self.wfile.write(b"Connected. You can close this tab.")

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", PORT), H)
    threading.Thread(target=srv.handle_request, daemon=True).start()
    cl = client()
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": cl["client_id"], "redirect_uri": REDIRECT, "response_type": "code", "scope": SCOPES,
        "access_type": "offline", "prompt": "consent"})
    print("Opening Google sign-in:", url)
    webbrowser.open(url)
    while "code" not in got and "error" not in got:
        time.sleep(0.3)
    if "error" in got:
        sys.exit("Sign-in cancelled: " + got["error"])
    t = post_form("https://oauth2.googleapis.com/token", {
        "code": got["code"], "client_id": cl["client_id"], "client_secret": cl["client_secret"],
        "redirect_uri": REDIRECT, "grant_type": "authorization_code"})
    t["expires_at"] = time.time() + t.get("expires_in", 3600)
    with open(TOKEN, "w") as f:
        json.dump(t, f)
    os.chmod(TOKEN, 0o600)
    print("Connected.")


def access_token():
    if not os.path.exists(TOKEN):
        sys.exit("Run `python3 youtube_upload.py connect` first.")
    t = json.load(open(TOKEN))
    if t.get("expires_at", 0) > time.time() + 60:
        return t["access_token"]
    cl = client()
    n = post_form("https://oauth2.googleapis.com/token", {
        "client_id": cl["client_id"], "client_secret": cl["client_secret"],
        "refresh_token": t["refresh_token"], "grant_type": "refresh_token"})
    t.update(access_token=n["access_token"], expires_at=time.time() + n.get("expires_in", 3600))
    with open(TOKEN, "w") as f:
        json.dump(t, f)
    return t["access_token"]


def upload(path, title, description, tags):
    """Resumable videos.insert: step 1 sends the metadata and gets an upload URL, step 2 sends the bytes."""
    tag_list = [t.lstrip("#") for t in tags.split() if t.strip("#")]
    meta = {"snippet": {"title": title[:100], "description": description[:4900], "tags": tag_list[:15], "categoryId": "20"},
            "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False}}
    token = access_token()
    size = os.path.getsize(path)
    init = urllib.request.Request(
        "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        data=json.dumps(meta).encode(), method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8",
                 "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)})
    with urllib.request.urlopen(init, timeout=60) as r:
        location = r.headers["Location"]
    with open(path, "rb") as f:
        put = urllib.request.Request(location, data=f.read(), method="PUT", headers={"Content-Type": "video/mp4"})
    with urllib.request.urlopen(put, timeout=900) as r:
        video = json.loads(r.read())
    print(f"Uploaded: https://www.youtube.com/shorts/{video['id']} (privacy: {video['status']['privacyStatus']})")
    return video["id"]


def status(video_id):
    """Confirm the upload: processing state, privacy and public URL, via videos.list."""
    d = api_get("https://www.googleapis.com/youtube/v3/videos?" + urllib.parse.urlencode(
        {"part": "status,snippet,processingDetails", "id": video_id}), access_token())
    if not d.get("items"):
        sys.exit("Not found on the channel.")
    v = d["items"][0]
    print(json.dumps({"id": v["id"], "title": v["snippet"]["title"], "uploadStatus": v["status"]["uploadStatus"],
                      "privacyStatus": v["status"]["privacyStatus"], "url": f"https://www.youtube.com/shorts/{v['id']}"}, indent=1))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "connect":
        connect()
    elif cmd == "upload" and len(sys.argv) >= 4:
        vid = upload(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else "", sys.argv[5] if len(sys.argv) > 5 else "")
        time.sleep(5)
        status(vid)
    elif cmd == "status" and len(sys.argv) == 3:
        status(sys.argv[2])
    else:
        sys.exit(__doc__)
