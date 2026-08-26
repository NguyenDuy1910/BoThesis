# BoThesis mobile

Flutter client for the BoThesis enterprise knowledge assistant. The app mirrors
the web chat's OpenResponses event model and renders text, reasoning summaries,
tool activity, citations, errors, and retries as the backend stream arrives.

## Run on a physical iPhone

Start the BoThesis API on an interface reachable from the phone, connect the
Mac and iPhone to the same network, and replace the values below:

```bash
cd /Users/nguyenduy/Documents/utex/BoThesis/backend
BOTHESIS_HOST=0.0.0.0 uv run python main.py
```

```bash
cd /Users/nguyenduy/Documents/utex/BoThesis/app
flutter pub get
flutter run -d <iphone-device-id> \
  --dart-define=BOTHESIS_API_URL=http://<mac-lan-ip>:8000 \
  --dart-define=BOTHESIS_TENANT_ID=<tenant-id> \
  --dart-define=BOTHESIS_USER_ID=<user-id>
```

List connected device identifiers with `flutter devices`.

The temporary API default uses this development Mac's Bonjour hostname,
`http://Nguyens-MacBook-Pro.local:8000`, and the identity defaults match
`web/.env.local`. Use the `BOTHESIS_API_URL` override on another Mac. Plain HTTP
and local-network access are enabled for development in `ios/Runner/Info.plist`;
production builds should use HTTPS and tighten the App Transport Security
policy.

## Checks

```bash
dart format .
flutter analyze
```
