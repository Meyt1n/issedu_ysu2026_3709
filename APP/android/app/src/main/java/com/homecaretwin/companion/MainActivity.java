package com.homecaretwin.companion;

import android.os.Bundle;
import android.graphics.Color;
import android.view.View;
import android.webkit.WebSettings;
import android.webkit.WebView;

import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowCompat;
import androidx.core.view.WindowInsetsCompat;
import androidx.core.view.WindowInsetsControllerCompat;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        // 让 WebView 绘制到状态栏与手势导航栏之下。实际内容的安全边距会在
        // configureEdgeToEdge() 中作为 CSS 变量交给前端，背景因此能铺满全屏，
        // 文字和底部导航仍不会被系统栏遮挡。
        WindowCompat.setDecorFitsSystemWindows(getWindow(), false);
        super.onCreate(savedInstanceState);

        configureEdgeToEdge();

        // Android Debug builds use the HTTPS Capacitor origin so cookies and the
        // service worker keep their normal semantics. Allowing a private-LAN HTTP
        // API therefore has to be explicit at the WebView layer as well. The
        // server URL validator still rejects public cleartext targets, and the
        // BuildConfig guard keeps this setting out of Release behavior.
        if (BuildConfig.DEBUG && getBridge() != null && getBridge().getWebView() != null) {
            WebSettings settings = getBridge().getWebView().getSettings();
            settings.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        }
    }

    private void configureEdgeToEdge() {
        if (getBridge() == null || getBridge().getWebView() == null) {
            return;
        }

        // BridgeActivity 创建 WebView 后会应用自己的窗口配置，因此必须在此再次
        // 设置，确保 WebView 不会重新被限制在状态栏和导航栏之间。
        WindowCompat.setDecorFitsSystemWindows(getWindow(), false);
        getWindow().setStatusBarColor(Color.TRANSPARENT);
        getWindow().setNavigationBarColor(Color.TRANSPARENT);

        WindowInsetsControllerCompat controller = new WindowInsetsControllerCompat(
            getWindow(),
            getWindow().getDecorView()
        );
        // 默认浅色纸笺主题使用深色系统栏图标；深色模式仍会保持透明系统栏，
        // 并由系统夜间主题提供相应的对比度处理。
        controller.setAppearanceLightStatusBars(true);
        controller.setAppearanceLightNavigationBars(true);

        WebView webView = getBridge().getWebView();
        View webViewParent = (View) webView.getParent();
        // Capacitor 8 在较旧 WebView 上会为 parent 追加系统栏 padding，造成
        // 页面视觉上缺少顶部和底部两条区域。接管 parent 的 Insets 分发：保留
        // 键盘避让，但让 WebView 本身始终覆盖整个窗口。
        ViewCompat.setOnApplyWindowInsetsListener(webViewParent, (view, insets) -> {
            applySafeAreaInsets(webView, insets);
            Insets imeInsets = insets.getInsets(WindowInsetsCompat.Type.ime());
            view.setPadding(0, 0, 0, insets.isVisible(WindowInsetsCompat.Type.ime()) ? imeInsets.bottom : 0);
            return new WindowInsetsCompat.Builder(insets)
                .setInsets(
                    WindowInsetsCompat.Type.systemBars() | WindowInsetsCompat.Type.displayCutout(),
                    Insets.of(0, 0, 0, 0)
                )
                .build();
        });
        ViewCompat.requestApplyInsets(webViewParent);
        // 部分厂商 WebView 在监听器注册前已分发首次 Insets；主动补一次，防止
        // CSS 回退为 0 而使内容贴到状态栏或手势条上。
        webView.post(() -> {
            WindowInsetsCompat initialInsets = ViewCompat.getRootWindowInsets(webViewParent);
            if (initialInsets != null) {
                applySafeAreaInsets(webView, initialInsets);
            }
        });
    }

    private void applySafeAreaInsets(WebView webView, WindowInsetsCompat insets) {
        Insets bars = insets.getInsets(
            WindowInsetsCompat.Type.systemBars() | WindowInsetsCompat.Type.displayCutout()
        );
        float density = getResources().getDisplayMetrics().density;
        String cssVariables = String.format(
            java.util.Locale.US,
            "(function(){var r=document.documentElement;if(!r)return;"
                + "r.style.setProperty('--safe-area-inset-top','%.1fpx');"
                + "r.style.setProperty('--safe-area-inset-right','%.1fpx');"
                + "r.style.setProperty('--safe-area-inset-bottom','%.1fpx');"
                + "r.style.setProperty('--safe-area-inset-left','%.1fpx');})()",
            bars.top / density,
            bars.right / density,
            bars.bottom / density,
            bars.left / density
        );
        webView.post(() -> webView.evaluateJavascript(cssVariables, null));
    }
}
