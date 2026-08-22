# BoThesis mobile app

Flutter client for the BoThesis knowledge assistant.

## Run

```bash
cd app/bothesis
flutter pub get
flutter analyze
flutter run
```

The default development API URL is `http://10.0.2.2:8000/`, which reaches
the host machine from an Android emulator. Override it for another environment:

```bash
flutter run --dart-define=BOTHESIS_API_BASE_URL=https://api.example.com/
```

## Structure

- `lib/app`: application widget and routes
- `lib/config`: build-time environment configuration
- `lib/theme`: Material theme
- `lib/models`: app data models
- `lib/services`: HTTP API client
- `lib/features`: bootstrap, chat, and settings screens
- `lib/shared`: reusable UI widgets

When the BoThesis chat API contract is available, add its request and response
models under `lib/models`, add endpoint methods to `lib/services/api_client.dart`,
and call them from the chat feature. Keep source citations and any permission
metadata in the response models so the UI can render grounded answers.
