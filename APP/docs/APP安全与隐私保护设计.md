# APP安全与隐私保护设计

> 本文档是家健镜系统 APP 安全与隐私保护的完整设计说明，覆盖数据加密、身份认证、权限控制、隐私合规。

## 1. 安全概述

### 1.1 设计目标

1. 数据加密：敏感数据加密存储和传输
2. 身份安全：安全的用户认证机制
3. 权限控制：最小权限原则
4. 隐私合规：符合个人信息保护法
5. 防攻击：防止常见安全攻击

### 1.2 安全等级

| 数据类型 | 加密要求 | 访问控制 |
| --- | --- | --- |
| 健康数据 | AES-256 加密 | 严格权限 |
| 个人信息 | AES-256 加密 | 严格权限 |
| 账号密码 | bcrypt 哈希 | 仅本人 |
| 用药记录 | AES-256 加密 | 家庭成员 |
| 设备信息 | 明文 | 管理员 |

## 2. 数据加密

### 2.1 本地存储加密

```dart
// Flutter 安全存储
class SecureStorage {
  static const _storage = FlutterSecureStorage();

  static Future<void> write(String key, String value) async {
    await _storage.write(
      key: key,
      value: value,
      aOptions: AndroidOptions(
        encryptedSharedPreferences: true,
      ),
      iOptions: IOSOptions(
        accessibility: KeychainAccessibility.first_unlock,
      ),
    );
  }

  static Future<String?> read(String key) async {
    return _storage.read(key: key);
  }

  static Future<void> delete(String key) async {
    await _storage.delete(key: key);
  }
}
```

### 2.2 数据库加密

```dart
// SQLCipher 加密数据库
class EncryptedDatabase {
  static Database? _db;

  static Future<Database> getInstance() async {
    if (_db != null) return _db!;

    final password = await SecureStorage.read('db_password');
    _db = await databaseFactory.openDatabase(
      'homecare_encrypted.db',
      options: OpenDatabaseOptions(
        version: 1,
        onConfigure: (db) async {
          await db.execute("PRAGMA key = '$password'");
        },
      ),
    );
    return _db!;
  }
}
```

### 2.3 传输加密

- 所有 API 请求使用 HTTPS
- 证书锁定（Certificate Pinning）
- 敏感数据额外加密

```dart
class SecureHttpClient {
  static Dio createClient() {
    final dio = Dio();

    // 证书锁定
    (dio.httpClientAdapter as DefaultHttpClientAdapter).onHttpClientCreate =
        (client) {
      client.badCertificateCallback = (cert, host, port) {
        return cert.pem == expectedCertificate;
      };
      return client;
    };

    return dio;
  }
}
```

## 3. 身份认证

### 3.1 Token 管理

```dart
class TokenManager {
  static const _accessTokenKey = 'access_token';
  static const _refreshTokenKey = 'refresh_token';

  static Future<void> saveTokens(String access, String refresh) async {
    await SecureStorage.write(_accessTokenKey, access);
    await SecureStorage.write(_refreshTokenKey, refresh);
  }

  static Future<String?> getAccessToken() async {
    return SecureStorage.read(_accessTokenKey);
  }

  static Future<void> clearTokens() async {
    await SecureStorage.delete(_accessTokenKey);
    await SecureStorage.delete(_refreshTokenKey);
  }

  static Future<String?> refreshToken() async {
    final refresh = await SecureStorage.read(_refreshTokenKey);
    if (refresh == null) return null;

    final response = await ApiClient.post('/auth/refresh', {
      'refresh_token': refresh,
    });

    if (response.statusCode == 200) {
      await saveTokens(response.data['access'], response.data['refresh']);
      return response.data['access'];
    }
    return null;
  }
}
```

### 3.2 生物识别

```dart
class BiometricAuth {
  static final _auth = LocalAuthentication();

  static Future<bool> canAuthenticate() async {
    return await _auth.canCheckBiometrics;
  }

  static Future<bool> authenticate(String reason) async {
    try {
      return await _auth.authenticate(
        localizedReason: reason,
        options: AuthenticationOptions(
          biometricOnly: true,
          useErrorDialogs: true,
          stickyAuth: true,
        ),
      );
    } catch (e) {
      return false;
    }
  }
}
```

## 4. 权限控制

### 4.1 运行时权限

```dart
class PermissionManager {
  static Future<bool> requestCamera() async {
    final status = await Permission.camera.request();
    return status.isGranted;
  }

  static Future<bool> requestStorage() async {
    final status = await Permission.storage.request();
    return status.isGranted;
  }

  static Future<bool> requestNotifications() async {
    final status = await Permission.notification.request();
    return status.isGranted;
  }

  static Future<bool> requestLocation() async {
    final status = await Permission.locationWhenInUse.request();
    return status.isGranted;
  }
}
```

### 4.2 数据权限

```dart
class DataPermission {
  static bool canViewMedicine(User user, Medicine medicine) {
    return user.householdId == medicine.householdId;
  }

  static bool canEditMedicine(User user, Medicine medicine) {
    return user.householdId == medicine.householdId &&
        (user.role == 'admin' || user.id == medicine.createdBy);
  }

  static bool canViewHealthRecord(User user, HealthRecord record) {
    return user.householdId == record.householdId &&
        (user.id == record.memberId || user.role == 'admin');
  }
}
```

## 5. 隐私保护

### 5.1 隐私政策

- 明确收集哪些数据
- 明确数据用途
- 明确数据存储期限
- 用户可查看和删除数据
- 用户可导出数据

### 5.2 数据最小化

```dart
// 只收集必要数据
class UserProfile {
  final String id;
  final String nickname;
  final String? avatar;
  // 不收集：真实姓名、身份证号（除非必要）
}
```

### 5.3 数据脱敏

```dart
class DataMasking {
  static String maskPhone(String phone) {
    if (phone.length != 11) return phone;
    return '${phone.substring(0, 3)}****${phone.substring(7)}';
  }

  static String maskEmail(String email) {
    final parts = email.split('@');
    if (parts.length != 2) return email;
    final name = parts[0];
    return '${name[0]}***@${parts[1]}';
  }

  static String maskIdCard(String idCard) {
    if (idCard.length != 18) return idCard;
    return '${idCard.substring(0, 6)}********${idCard.substring(14)}';
  }
}
```

## 6. 防攻击

### 6.1 防截屏

```dart
class SecureScreen {
  static final _channel = MethodChannel('com.homecare/secure');

  static Future<void> enableSecure() async {
    await _channel.invokeMethod('enableSecure');
  }

  static Future<void> disableSecure() async {
    await _channel.invokeMethod('disableSecure');
  }
}
```

### 6.2 越狱/Root 检测

```dart
class SecurityCheck {
  static Future<bool> isJailbroken() async {
    try {
      final result = await MethodChannel('com.homecare/security')
          .invokeMethod('isJailbroken');
      return result as bool;
    } catch (e) {
      return false;
    }
  }
}
```

### 6.3 代码混淆

```yaml
# android/app/build.gradle
android {
    buildTypes {
        release {
            minifyEnabled true
            shrinkResources true
            proguardFiles getDefaultProguardFile('proguard-android-optimize.txt'),
                         'proguard-rules.pro'
        }
    }
}
```

## 7. APP安全检查清单

- [ ] 本地数据加密
- [ ] 数据库加密
- [ ] HTTPS 传输
- [ ] 证书锁定
- [ ] Token 安全存储
- [ ] 生物识别
- [ ] 运行时权限
- [ ] 数据权限控制
- [ ] 隐私政策
- [ ] 数据最小化
- [ ] 数据脱敏
- [ ] 防截屏
- [ ] 越狱检测
- [ ] 代码混淆
- [ ] 安全更新机制

---

*安全与隐私是健康应用的生命线。全方位的安全保护，让用户的健康数据安全无忧。*
