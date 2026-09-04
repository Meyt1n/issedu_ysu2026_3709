# APP导航与路由设计

> 本文档是家健镜 APP 导航与路由的完整设计说明，覆盖路由配置、导航结构、深链接、权限守卫、转场动画。面向移动端开发者，作为导航实现的权威依据。

## 1. 导航概述

### 1.1 设计目标

1. **清晰层级**：用户随时知道自己在哪里
2. **快速到达**：核心功能 3 次点击内可达
3. **状态保持**：切换 Tab 时保持页面状态
4. **深链接**：支持外部链接直接打开指定页面
5. **权限控制**：未登录用户自动跳转登录页

### 1.2 技术选型

- **路由**：go_router（声明式、支持深链接）
- **导航**：BottomNavigationBar + 嵌套路由
- **状态保持**：IndexedStack + AutomaticKeepAliveClientMixin

## 2. 路由配置

### 2.1 路由表

```dart
class AppRoutes {
  static const String splash = '/';
  static const String login = '/login';
  static const String register = '/register';
  static const String home = '/home';
  static const String medicines = '/medicines';
  static const String medicineDetail = '/medicines/:id';
  static const String medicineAdd = '/medicines/add';
  static const String members = '/members';
  static const String memberDetail = '/members/:id';
  static const String memberAdd = '/members/add';
  static const String risks = '/risks';
  static const String chat = '/chat';
  static const String vision = '/vision';
  static const String profile = '/profile';
  static const String settings = '/settings';
  static const String householdSettings = '/household/settings';
  static const String invitations = '/invitations';
}
```

### 2.2 GoRouter 配置

```dart
final GlobalKey<NavigatorState> _rootNavigatorKey =
    GlobalKey<NavigatorState>(debugLabel: 'root');
final GlobalKey<NavigatorState> _shellNavigatorKey =
    GlobalKey<NavigatorState>(debugLabel: 'shell');

GoRouter createRouter(AuthProvider authProvider) {
  return GoRouter(
    navigatorKey: _rootNavigatorKey,
    initialLocation: AppRoutes.splash,
    debugLogDiagnostics: kDebugMode,
    redirect: (context, state) {
      final isLoggedIn = authProvider.isLoggedIn;
      final isGoingToAuth = state.matchedLocation == AppRoutes.login ||
          state.matchedLocation == AppRoutes.register;
      final isSplash = state.matchedLocation == AppRoutes.splash;

      if (isSplash) return null;
      if (!isLoggedIn && !isGoingToAuth) return AppRoutes.login;
      if (isLoggedIn && isGoingToAuth) return AppRoutes.home;
      return null;
    },
    refreshListenable: authProvider,
    routes: [
      GoRoute(
        path: AppRoutes.splash,
        builder: (context, state) => const SplashPage(),
      ),
      GoRoute(
        path: AppRoutes.login,
        builder: (context, state) => const LoginPage(),
      ),
      GoRoute(
        path: AppRoutes.register,
        builder: (context, state) => const RegisterPage(),
      ),
      ShellRoute(
        navigatorKey: _shellNavigatorKey,
        builder: (context, state, child) => MainShell(child: child),
        routes: [
          GoRoute(
            path: AppRoutes.home,
            builder: (context, state) => const HomePage(),
          ),
          GoRoute(
            path: AppRoutes.medicines,
            builder: (context, state) => const MedicinesPage(),
            routes: [
              GoRoute(
                path: 'add',
                builder: (context, state) => const MedicineAddPage(),
              ),
              GoRoute(
                path: ':id',
                builder: (context, state) => MedicineDetailPage(
                  medicineId: state.pathParameters['id']!,
                ),
              ),
            ],
          ),
          GoRoute(
            path: AppRoutes.members,
            builder: (context, state) => const MembersPage(),
            routes: [
              GoRoute(
                path: ':id',
                builder: (context, state) => MemberDetailPage(
                  memberId: state.pathParameters['id']!,
                ),
              ),
            ],
          ),
          GoRoute(
            path: AppRoutes.risks,
            builder: (context, state) => const RisksPage(),
          ),
          GoRoute(
            path: AppRoutes.profile,
            builder: (context, state) => const ProfilePage(),
          ),
        ],
      ),
      GoRoute(
        path: AppRoutes.chat,
        builder: (context, state) => const ChatPage(),
      ),
      GoRoute(
        path: AppRoutes.vision,
        builder: (context, state) => const VisionPage(),
      ),
      GoRoute(
        path: AppRoutes.settings,
        builder: (context, state) => const SettingsPage(),
      ),
    ],
  );
}
```

## 3. 主导航结构

### 3.1 底部导航

```dart
class MainShell extends StatelessWidget {
  final Widget child;

  const MainShell({super.key, required this.child});

  static const _tabs = [
    _NavItem(
      path: AppRoutes.home,
      icon: Icons.home_outlined,
      activeIcon: Icons.home,
      label: '首页',
    ),
    _NavItem(
      path: AppRoutes.medicines,
      icon: Icons.medication_outlined,
      activeIcon: Icons.medication,
      label: '药品',
    ),
    _NavItem(
      path: AppRoutes.members,
      icon: Icons.people_outline,
      activeIcon: Icons.people,
      label: '成员',
    ),
    _NavItem(
      path: AppRoutes.risks,
      icon: Icons.warning_amber_outlined,
      activeIcon: Icons.warning,
      label: '风险',
    ),
    _NavItem(
      path: AppRoutes.profile,
      icon: Icons.person_outline,
      activeIcon: Icons.person,
      label: '我的',
    ),
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: IndexedStack(
        index: _currentIndex(context),
        children: const [
          KeepAliveWrapper(child: HomePage()),
          KeepAliveWrapper(child: MedicinesPage()),
          KeepAliveWrapper(child: MembersPage()),
          KeepAliveWrapper(child: RisksPage()),
          KeepAliveWrapper(child: ProfilePage()),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _currentIndex(context),
        onDestinationSelected: (index) {
          context.go(_tabs[index].path);
        },
        destinations: _tabs
            .map((tab) => NavigationDestination(
                  icon: Icon(tab.icon),
                  selectedIcon: Icon(tab.activeIcon),
                  label: tab.label,
                ))
            .toList(),
      ),
    );
  }

  int _currentIndex(BuildContext context) {
    final location = GoRouterState.of(context).matchedLocation;
    for (var i = 0; i < _tabs.length; i++) {
      if (location.startsWith(_tabs[i].path)) return i;
    }
    return 0;
  }
}
```

### 3.2 页面状态保持

```dart
class KeepAliveWrapper extends StatefulWidget {
  final Widget child;

  const KeepAliveWrapper({super.key, required this.child});

  @override
  State<KeepAliveWrapper> createState() => _KeepAliveWrapperState();
}

class _KeepAliveWrapperState extends State<KeepAliveWrapper>
    with AutomaticKeepAliveClientMixin {
  @override
  bool get wantKeepAlive => true;

  @override
  Widget build(BuildContext context) {
    super.build(context);
    return widget.child;
  }
}
```

## 4. 权限守卫

### 4.1 路由级权限

```dart
class AuthGuard extends GoRoute {
  AuthGuard({
    required super.path,
    required super.builder,
    List<GoRoute> routes = const [],
  }) : super(
          redirect: (context, state) {
            final auth = context.read<AuthProvider>();
            if (!auth.isLoggedIn) {
              return AppRoutes.login;
            }
            return null;
          },
          routes: routes,
        );
}

class HouseholdMemberGuard extends GoRoute {
  HouseholdMemberGuard({
    required super.path,
    required super.builder,
  }) : super(
          redirect: (context, state) {
            final auth = context.read<AuthProvider>();
            final household = context.read<HouseholdProvider>();
            final householdId = state.pathParameters['householdId'];

            if (!auth.isLoggedIn) return AppRoutes.login;
            if (householdId != null &&
                !household.isMember(householdId, auth.currentUser!.id)) {
              return AppRoutes.home;
            }
            return null;
          },
        );
}
```

### 4.2 页面级权限

```dart
class PermissionHandler extends StatelessWidget {
  final Widget child;
  final bool Function(BuildContext) permissionCheck;
  final Widget? deniedWidget;

  const PermissionHandler({
    super.key,
    required this.child,
    required this.permissionCheck,
    this.deniedWidget,
  });

  @override
  Widget build(BuildContext context) {
    if (permissionCheck(context)) return child;
    return deniedWidget ?? const _DefaultDeniedPage();
  }
}
```

## 5. 深链接

### 5.1 深链接配置

```dart
// Android: AndroidManifest.xml
// <intent-filter>
//   <action android:name="android.intent.action.VIEW" />
//   <category android:name="android.intent.category.DEFAULT" />
//   <category android:name="android.intent.category.BROWSABLE" />
//   <data android:scheme="https" android:host="homecare.example.com" />
// </intent-filter>

// iOS: Info.plist
// <key>CFBundleURLTypes</key>
// <array>
//   <dict>
//     <key>CFBundleURLSchemes</key>
//     <array>
//       <string>homecare</string>
//     </array>
//   </dict>
// </array>

GoRouter createRouter() {
  return GoRouter(
    // ...
    routes: [
      GoRoute(
        path: '/share/medicine/:id',
        builder: (context, state) => MedicineDetailPage(
          medicineId: state.pathParameters['id']!,
        ),
      ),
      GoRoute(
        path: '/invite/:code',
        builder: (context, state) => InvitePage(
          code: state.pathParameters['code']!,
        ),
      ),
    ],
  );
}
```

### 5.2 推送通知跳转

```dart
class NotificationService {
  Future<void> handleNotification(Map<String, dynamic> payload) async {
    final type = payload['type'];
    final id = payload['id'];

    switch (type) {
      case 'medicine_reminder':
        _router.go('/medicines/$id');
        break;
      case 'risk_alert':
        _router.go('/risks');
        break;
      case 'chat_message':
        _router.go('/chat');
        break;
      case 'household_invite':
        _router.go('/invitations');
        break;
      default:
        _router.go('/home');
    }
  }
}
```

## 6. 转场动画

### 6.1 自定义转场

```dart
CustomTransitionPage buildPageWithDefaultTransition({
  required LocalKey key,
  required Widget child,
}) {
  return CustomTransitionPage(
    key: key,
    child: child,
    transitionsBuilder: (context, animation, secondaryAnimation, child) {
      return FadeTransition(
        opacity: CurveTween(curve: Curves.easeInOut).animate(animation),
        child: child,
      );
    },
  );
}

CustomTransitionPage slideFromRight({
  required LocalKey key,
  required Widget child,
}) {
  return CustomTransitionPage(
    key: key,
    child: child,
    transitionsBuilder: (context, animation, secondaryAnimation, child) {
      return SlideTransition(
        position: Tween<Offset>(
          begin: const Offset(1, 0),
          end: Offset.zero,
        ).animate(CurvedAnimation(
          parent: animation,
          curve: Curves.easeInOut,
        )),
        child: child,
      );
    },
  );
}
```

## 7. 导航检查清单

- [ ] 路由配置完整
- [ ] 登录重定向正确
- [ ] Tab 切换状态保持
- [ ] 深链接可正常跳转
- [ ] 推送通知跳转正确
- [ ] 权限守卫生效
- [ ] 转场动画流畅
- [ ] 返回栈管理正确
- [ ] 错误页面友好
- [ ] 路由有单元测试

---

*清晰的导航是 APP 体验的骨架。让用户随时知道自己在哪，想去哪就去哪。*
