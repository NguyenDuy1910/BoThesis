abstract final class AppConfig {
  /// Override with --dart-define=BOTHESIS_API_BASE_URL=https://api.example.com/
  static const apiBaseUrl = String.fromEnvironment(
    'BOTHESIS_API_BASE_URL',
    defaultValue: 'http://10.0.2.2:8000/',
  );

  static Uri get apiBaseUri => Uri.parse(apiBaseUrl);
}
