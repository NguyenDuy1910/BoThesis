abstract final class AppConfig {
  // Keep the temporary development identity aligned with web/.env.local.
  // BOTHESIS_* remains the preferred mobile override; accepting the web keys
  // makes shared build configurations work without duplicating values.
  static const _webApiBaseUrl = String.fromEnvironment(
    'NEXT_PUBLIC_BOTHESIS_API_URL',
    // This development default is reachable from a physical iPhone on the
    // same network. Override BOTHESIS_API_URL for other development hosts and
    // every deployed environment.
    defaultValue: 'http://Nguyens-MacBook-Pro.local:8000',
  );
  static const _webTenantId = String.fromEnvironment(
    'NEXT_PUBLIC_BOTHESIS_TENANT_ID',
    defaultValue: '00000000-0000-0000-0000-000000000001',
  );
  static const _webUserId = String.fromEnvironment(
    'NEXT_PUBLIC_BOTHESIS_USER_ID',
    defaultValue: '00000000-0000-0000-0000-000000000002',
  );

  static const apiBaseUrl = String.fromEnvironment(
    'BOTHESIS_API_URL',
    defaultValue: _webApiBaseUrl,
  );

  static const tenantId = String.fromEnvironment(
    'BOTHESIS_TENANT_ID',
    defaultValue: _webTenantId,
  );
  static const userId = String.fromEnvironment(
    'BOTHESIS_USER_ID',
    defaultValue: _webUserId,
  );

  static Uri get apiBaseUri => Uri.parse(
    apiBaseUrl.endsWith('/')
        ? apiBaseUrl.substring(0, apiBaseUrl.length - 1)
        : apiBaseUrl,
  );

  static bool get isConfigured =>
      apiBaseUri.hasScheme &&
      tenantId.trim().isNotEmpty &&
      userId.trim().isNotEmpty;
}
