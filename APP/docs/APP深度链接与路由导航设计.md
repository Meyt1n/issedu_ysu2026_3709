# APP深度链接与路由导航设计

> 本文档是家健镜系统 APP 深度链接与路由导航的完整设计说明，覆盖路由配置、深度链接、导航管理、过渡动画、权限拦截。

## 1. 概述

### 1.1 设计目标

1. 路由配置清晰
2. 支持深度链接
3. 导航可测试
4. 过渡流畅
5. 权限可控

### 1.2 路由类型

| 类型 | 说明 | 示例 |
| --- | --- | --- |
| 页面路由 | APP 内页面跳转 | /medicines |
| 深度链接 | 外部链接打开 | https://app.homecare.com/medicines/123 |
| 通用链接 | iOS Universal Links | app.homecare.com |
| App Links | Android App Links | app.homecare.com |
| 自定义 Scheme | 自定义协议 | homecare://medicines |

## 2. 路由配置

### 2.1 路由定义

```dart
class AppRoutes {
  static const String home = '/';
  static const String login = '/login';
  static const String medicines = '/medicines';
  static const String medicineDetail = '/medicines/:id';
  static const String addMedicine = '/medicines/add';
  static const String health = '/health';
  static const String healthDetail = '/health/:type';
  static const String family = '/family';
  static const String profile = '/profile';
  static const String settings = '/settings';
  static const String report = '/report';
  static const String reportDetail = '/report/:id';
  static const String medicineReminder = '/reminders/medicines/:id';
}
```

### 2.2 路由表

```dart
class AppRouter {
  static Route<dynamic> generateRoute(RouteSettings settings) {
    final uri = Uri.parse(settings.name ?? '');

    switch (uri.path) {
      case AppRoutes.home:
        return MaterialPageRoute(builder: (_) => HomePage());

      case AppRoutes.login:
        return MaterialPageRoute(builder: (_) => LoginPage());

      case AppRoutes.medicines:
        return MaterialPageRoute(builder: (_) => MedicinesPage());

      default:
        if (uri.path.startsWith('/medicines/')) {
          final id = uri.pathSegments[1];
          return MaterialPageRoute(
            builder: (_) => MedicineDetailPage(medicineId: id),
          );
        }
        return MaterialPageRoute(builder: (_) => NotFoundPage());
    }
  }
}
```

### 2.3 路由参数

```dart
class RouteParams {
  final Map<String, String> pathParams;
  final Map<String, String> queryParams;
  final dynamic arguments;

  RouteParams({
    this.pathParams = const {},
    this.queryParams = const {},
    this.arguments,
  });

  factory RouteParams.fromSettings(RouteSettings settings) {
    final uri = Uri.parse(settings.name ?? '');
    return RouteParams(
      pathParams: _extractPathParams(settings.name ?? ''),
      queryParams: uri.queryParameters,
      arguments: settings.arguments,
    );
  }

  static Map<String, String> _extractPathParams(String path) {
    // 从路径中提取参数
    return {};
  }

  String? operator [](String key) {
    return pathParams[key] ?? queryParams[key];
  }
}
```

## 3. 深度链接

### 3.1 深度链接处理

```dart
class DeepLinkHandler {
  static final DeepLinkHandler _instance = DeepLinkHandler._internal();
  factory DeepLinkHandler() => _instance;
  DeepLinkHandler._internal();

  final StreamController<Uri> _linkController = StreamController<Uri>.broadcast();
  Stream<Uri> get linkStream => _linkController.stream;

  Future<void> init() async {
    // 监听初始链接
    final initialLink = await getInitialLink();
    if (initialLink != null) {
      _handleLink(initialLink);
    }

    // 监听后续链接
    uriLinkStream.listen((uri) {
      _handleLink(uri);
    });
  }

  void _handleLink(Uri uri) {
    _linkController.add(uri);

    // 根据路径导航
    final route = _mapToRoute(uri);
    if (route != null) {
      navigatorKey.currentState?.pushNamed(route);
    }
  }

  String? _mapToRoute(Uri uri) {
    // https://app.homecare.com/medicines/123 -> /medicines/123
    if (uri.host == 'app.homecare.com') {
      return uri.path;
    }

    // homecare://medicines/123 -> /medicines/123
    if (uri.scheme == 'homecare') {
      return uri.path;
    }

    return null;
  }
}
```

### 3.2 iOS Universal Links 配置

```xml
<!-- apple-app-site-association -->
{
  "applinks": {
    "apps": [],
    "details": [
      {
        "appID": "TEAMID.com.homecare.app",
        "paths": [
          "/medicines/*",
          "/health/*",
          "/report/*",
          "/profile"
        ]
      }
    ]
  }
}
```

### 3.3 Android App Links 配置

```xml
<!-- AndroidManifest.xml -->
<activity
    android:name=".MainActivity"
    android:exported="true">
    <intent-filter android:autoVerify="true">
        <action android:name="android.intent.action.VIEW" />
        <category android:name="android.intent.category.DEFAULT" />
        <category android:name="android.intent.category.BROWSABLE" />
        <data
            android:scheme="https"
            android:host="app.homecare.com"
            android:pathPrefix="/medicines" />
    </intent-filter>
    <intent-filter>
        <action android:name="android.intent.action.VIEW" />
        <category android:name="android.intent.category.DEFAULT" />
        <category android:name="android.intent.category.BROWSABLE" />
        <data android:scheme="homecare" />
    </intent-filter>
</activity>
```

### 3.4 推送通知深度链接

```dart
class PushNotificationHandler {
  Future<void> handleNotification(Map<String, dynamic> message) async {
    final deepLink = message['data']['deep_link'];
    if (deepLink != null) {
      final uri = Uri.parse(deepLink);
      await DeepLinkHandler()._handleLink(uri);
    }
  }
}
```

## 4. 导航管理

### 4.1 全局 Navigator

```dart
class NavigationService {
  static final GlobalKey<NavigatorState> navigatorKey = GlobalKey<NavigatorState>();

  static Future<dynamic> navigateTo(String routeName, {dynamic arguments}) {
    return navigatorKey.currentState!.pushNamed(routeName, arguments: arguments);
  }

  static Future<dynamic> replaceWith(String routeName, {dynamic arguments}) {
    return navigatorKey.currentState!.pushReplacementNamed(routeName, arguments: arguments);
  }

  static void goBack() {
    navigatorKey.currentState!.pop();
  }

  static Future<dynamic> navigateToAndClear(String routeName) {
    return navigatorKey.currentState!.pushNamedAndRemoveUntil(
      routeName,
      (route) => false,
    );
  }
}
```

### 4.2 导航观察者

```dart
class NavigationObserver extends NavigatorObserver {
  final List<Route> _routeStack = [];

  @override
  void didPush(Route route, Route? previousRoute) {
    _routeStack.add(route);
    _logNavigation('push', route);
  }

  @override
  void didPop(Route route, Route? previousRoute) {
    _routeStack.remove(route);
    _logNavigation('pop', route);
  }

  @override
  void didReplace({Route? newRoute, Route? oldRoute}) {
    if (oldRoute != null) _routeStack.remove(oldRoute);
    if (newRoute != null) _routeStack.add(newRoute);
  }

  void _logNavigation(String action, Route route) {
    AnalyticsService.instance.logEvent(
      'screen_view',
      parameters: {'screen_name': route.settings.name},
    );
  }

  List<Route> get routeStack => List.unmodifiable(_routeStack);
}
```

### 4.3 路由守卫

```dart
class RouteGuard {
  static Future<bool> canNavigate(String routeName, BuildContext context) async {
    // 需要登录的路由
    final protectedRoutes = [
      AppRoutes.medicines,
      AppRoutes.health,
      AppRoutes.profile,
    ];

    if (protectedRoutes.contains(routeName) || _isProtectedPath(routeName)) {
      final isLoggedIn = await AuthService.instance.isLoggedIn();
      if (!isLoggedIn) {
        NavigationService.navigateTo(AppRoutes.login);
        return false;
      }
    }

    // 需要特定权限的路由
    if (routeName == AppRoutes.settings) {
      final hasPermission = await PermissionService.instance.hasPermission('settings');
      if (!hasPermission) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('没有权限访问')),
        );
        return false;
      }
    }

    return true;
  }

  static bool _isProtectedPath(String path) {
    return path.startsWith('/medicines/') ||
           path.startsWith('/health/') ||
           path.startsWith('/report/');
  }
}
```

## 5. 过渡动画

### 5.1 自定义转场

```dart
class FadePageRoute<T> extends PageRoute<T> {
  final WidgetBuilder builder;

  FadePageRoute({required this.builder});

  @override
  Color get barrierColor => Colors.black.withOpacity(0.5);

  @override
  String get barrierLabel => '';

  @override
  bool get maintainState => true;

  @override
  Duration get transitionDuration => Duration(milliseconds: 300);

  @override
  Widget buildPage(BuildContext context, Animation<double> animation, Animation<double> secondaryAnimation) {
    return builder(context);
  }

  @override
  Widget buildTransitions(BuildContext context, Animation<double> animation, Animation<double> secondaryAnimation, Widget child) {
    return FadeTransition(opacity: animation, child: child);
  }
}

class SlidePageRoute<T> extends PageRoute<T> {
  final WidgetBuilder builder;
  final SlideDirection direction;

  SlidePageRoute({required this.builder, this.direction = SlideDirection.left});

  @override
  Widget buildTransitions(BuildContext context, Animation<double> animation, Animation<double> secondaryAnimation, Widget child) {
    final begin = _getBeginOffset();
    final tween = Tween(begin: begin, end: Offset.zero)
        .chain(CurveTween(curve: Curves.easeInOut));
    return SlideTransition(position: animation.drive(tween), child: child);
  }

  Offset _getBeginOffset() {
    switch (direction) {
      case SlideDirection.left:
        return Offset(1.0, 0.0);
      case SlideDirection.right:
        return Offset(-1.0, 0.0);
      case SlideDirection.up:
        return Offset(0.0, 1.0);
      case SlideDirection.down:
        return Offset(0.0, -1.0);
    }
  }
}

enum SlideDirection { left, right, up, down }
```

### 5.2 共享元素动画

```dart
class HeroAnimationPage extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: GridView.builder(
        itemCount: 10,
        gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(crossAxisCount: 2),
        itemBuilder: (context, index) {
          return GestureDetector(
            onTap: () {
              Navigator.push(context, MaterialPageRoute(
                builder: (_) => DetailPage(id: index),
              ));
            },
            child: Hero(
              tag: 'image_$index',
              child: Image.network('https://example.com/image_$index.jpg'),
            ),
          );
        },
      ),
    );
  }
}

class DetailPage extends StatelessWidget {
  final int id;
  DetailPage({required this.id});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: Hero(
          tag: 'image_$id',
          child: Image.network('https://example.com/image_$id.jpg'),
        ),
      ),
    );
  }
}
```

## 6. 路由测试

### 6.1 路由测试

```dart
void main() {
  testWidgets('导航到药品详情页', (WidgetTester tester) async {
    await tester.pumpWidget(MaterialApp(
      onGenerateRoute: AppRouter.generateRoute,
      initialRoute: '/',
    ));

    // 导航到详情页
    await tester.tap(find.text('药品1'));
    await tester.pumpAndSettle();

    // 验证页面
    expect(find.text('药品详情'), findsOneWidget);
  });

  test('深度链接映射到路由', () {
    final handler = DeepLinkHandler();
    final uri = Uri.parse('https://app.homecare.com/medicines/123');
    final route = handler._mapToRoute(uri);
    expect(route, '/medicines/123');
  });
}
```

## 7. 路由导航检查清单

- [ ] 路由定义
- [ ] 路由表
- [ ] 路由参数
- [ ] 深度链接处理
- [ ] Universal Links
- [ ] App Links
- [ ] 推送深度链接
- [ ] 全局 Navigator
- [ ] 导航观察者
- [ ] 路由守卫
- [ ] 过渡动画
- [ ] 路由测试

---

*流畅的导航是 APP 体验的脉络。清晰路由、深度链接、优雅转场，让用户在页面间自由穿梭。*
