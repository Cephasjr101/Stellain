
## Firebase setup (optional but recommended — Render free tier wipes SQLite on redeploy)

1. Go to console.firebase.google.com → **Add project** (any name)
2. **Build → Firestore Database → Create database** → Production mode → choose region (europe-west1 recommended for Africa/EU latency)
3. **Project settings (gear icon) → Service accounts → Generate new private key** → downloads a JSON file
4. Render dashboard → your service → **Environment** → add:
   - Key:   `FIREBASE_SERVICE_ACCOUNT`
   - Value: the **entire contents of the JSON file on ONE line**
     (open it in a text editor, use find/replace to remove newlines, or run:
     `python -c "import json;print(json.dumps(json.load(open('serviceAccountKey.json'))))"` and copy the output)
5. Redeploy. Check the Render logs for: "✅ Connected to Firebase Firestore"

The app auto-detects Firebase. If the env var is missing or invalid,
it falls back to SQLite and logs a warning — the site never goes down.

Collections used: `items`, `orders` (auto-created on first write).
Images still save to local /uploads. For permanent image storage add Firebase Storage later.

## Photo storage (Firebase Storage)

The upload endpoint now saves photos to Firebase Storage automatically when
Firebase is connected — images survive redeploys and are served from Google's CDN.

1. Firebase console → **Build → Storage → Get started** → production mode
   (default bucket name: `<project-id>.appspot.com`)
2. Optional env var if your bucket name differs:
   `FIREBASE_STORAGE_BUCKET=your-bucket-name.appspot.com`
3. If `make_public()` fails in logs (uniform bucket-level access enabled),
   either disable it on the bucket (Permissions → uncheck "Enforce public
   access prevention") or keep the signed-URL fallback (works automatically).

If Storage isn't reachable, uploads fall back to local `/uploads` and the
site keeps working.
