# 算法设计-可解释性AI与模型理解

> 本文档是家健镜系统可解释性 AI 与模型理解的完整设计说明，覆盖特征重要性、SHAP、LIME、反事实解释、可视化。

## 1. 概述

### 1.1 设计目标

1. 模型决策可解释
2. 特征贡献可量化
3. 预测结果可追溯
4. 医生可理解
5. 满足合规要求

### 1.2 可解释性方法

| 方法 | 类型 | 说明 |
| --- | --- | --- |
| 特征重要性 | 全局 | 整体特征贡献 |
| SHAP | 全局+局部 | Shapley 值解释 |
| LIME | 局部 | 局部线性近似 |
| 反事实 | 局部 | 如何改变预测 |
| 部分依赖图 | 全局 | 特征与预测关系 |

## 2. 特征重要性

### 2.1 基于树模型

```python
import pandas as pd
import matplotlib.pyplot as plt

class FeatureImportance:
    def __init__(self, model):
        self.model = model

    def get_importance(self, feature_names: list) -> pd.DataFrame:
        importance = self.model.feature_importances_
        df = pd.DataFrame({
            'feature': feature_names,
            'importance': importance,
        })
        return df.sort_values('importance', ascending=False)

    def plot_importance(self, feature_names: list, top_n: int = 20):
        df = self.get_importance(feature_names).head(top_n)

        plt.figure(figsize=(10, 6))
        plt.barh(df['feature'], df['importance'])
        plt.xlabel('重要性')
        plt.title('特征重要性')
        plt.tight_layout()
        plt.savefig('feature_importance.png')
```

### 2.2 排列重要性

```python
from sklearn.inspection import permutation_importance

class PermutationImportance:
    def __init__(self, model):
        self.model = model

    def calculate(self, X, y, n_repeats: int = 10):
        result = permutation_importance(
            self.model,
            X,
            y,
            n_repeats=n_repeats,
            random_state=42,
            n_jobs=-1,
        )

        return pd.DataFrame({
            'feature': X.columns,
            'importance_mean': result.importances_mean,
            'importance_std': result.importances_std,
        }).sort_values('importance_mean', ascending=False)
```

## 3. SHAP 解释

### 3.1 SHAP 值计算

```python
import shap

class SHAPExplainer:
    def __init__(self, model):
        self.explainer = shap.TreeExplainer(model)

    def explain(self, X):
        shap_values = self.explainer.shap_values(X)
        return shap_values

    def summary_plot(self, X, max_display: int = 20):
        shap_values = self.explain(X)
        shap.summary_plot(
            shap_values,
            X,
            max_display=max_display,
            show=False,
        )
        plt.savefig('shap_summary.png', bbox_inches='tight')

    def force_plot(self, X, index: int):
        shap_values = self.explain(X)
        shap.force_plot(
            self.explainer.expected_value,
            shap_values[index],
            X.iloc[index],
            matplotlib=True,
            show=False,
        )
        plt.savefig(f'shap_force_{index}.png', bbox_inches='tight')

    def dependence_plot(self, X, feature: str):
        shap_values = self.explain(X)
        shap.dependence_plot(
            feature,
            shap_values,
            X,
            show=False,
        )
        plt.savefig(f'shap_dependence_{feature}.png', bbox_inches='tight')
```

### 3.2 SHAP 交互值

```python
class SHAPInteraction:
    def __init__(self, model):
        self.explainer = shap.TreeExplainer(model)

    def interaction_values(self, X):
        return self.explainer.shap_interaction_values(X)

    def interaction_plot(self, X, feature1: str, feature2: str):
        interactions = self.interaction_values(X)
        shap.dependence_plot(
            (feature1, feature2),
            interactions,
            X,
            show=False,
        )
        plt.savefig(f'shap_interaction_{feature1}_{feature2}.png')
```

## 4. LIME 解释

### 4.1 LIME 解释器

```python
import lime
import lime.lime_tabular

class LIMEExplainer:
    def __init__(self, training_data, feature_names, class_names):
        self.explainer = lime.lime_tabular.LimeTabularExplainer(
            training_data=training_data,
            feature_names=feature_names,
            class_names=class_names,
            mode='classification',
        )

    def explain_instance(self, instance, predict_fn, num_features: int = 10):
        exp = self.explainer.explain_instance(
            instance,
            predict_fn,
            num_features=num_features,
        )
        return exp

    def plot_explanation(self, exp, save_path: str):
        fig = exp.as_pyplot_figure()
        fig.savefig(save_path, bbox_inches='tight')
        plt.close(fig)

    def get_explanation_list(self, exp):
        return exp.as_list()
```

### 4.2 LIME 文本解释

```python
import lime.lime_text

class LIMETextExplainer:
    def __init__(self, class_names):
        self.explainer = lime.lime_text.LimeTextExplainer(
            class_names=class_names,
        )

    def explain(self, text, predict_fn, num_features: int = 10):
        exp = self.explainer.explain_instance(
            text,
            predict_fn,
            num_features=num_features,
        )
        return exp
```

## 5. 反事实解释

### 5.1 反事实生成

```python
import numpy as np

class CounterfactualExplainer:
    def __init__(self, model, feature_ranges):
        self.model = model
        self.feature_ranges = feature_ranges

    def generate_counterfactual(
        self,
        instance,
        target_class,
        max_iterations: int = 1000,
        step_size: float = 0.01,
    ):
        current = instance.copy()

        for _ in range(max_iterations):
            prediction = self.model.predict([current])[0]

            if prediction == target_class:
                return current

            # 梯度下降寻找反事实
            gradient = self._compute_gradient(current, target_class)
            current = current - step_size * gradient

            # 限制在特征范围内
            current = self._clip_to_range(current)

        return None  # 未找到反事实

    def _compute_gradient(self, instance, target_class):
        # 数值梯度
        epsilon = 1e-5
        gradient = np.zeros_like(instance)

        for i in range(len(instance)):
            instance_plus = instance.copy()
            instance_plus[i] += epsilon
            instance_minus = instance.copy()
            instance_minus[i] -= epsilon

            pred_plus = self.model.predict_proba([instance_plus])[0][target_class]
            pred_minus = self.model.predict_proba([instance_minus])[0][target_class]

            gradient[i] = (pred_plus - pred_minus) / (2 * epsilon)

        return gradient
```

### 5.2 反事实解释展示

```python
class CounterfactualExplainer:
    def explain(self, original, counterfactual, feature_names):
        changes = []
        for i, (orig, cf) in enumerate(zip(original, counterfactual)):
            if abs(orig - cf) > 1e-6:
                changes.append({
                    'feature': feature_names[i],
                    'original': orig,
                    'counterfactual': cf,
                    'change': cf - orig,
                })
        return changes
```

## 6. 部分依赖图

### 6.1 PDP 计算

```python
from sklearn.inspection import partial_dependence, PartialDependenceDisplay

class PartialDependence:
    def __init__(self, model):
        self.model = model

    def plot(self, X, features: list):
        PartialDependenceDisplay.from_estimator(
            self.model,
            X,
            features=features,
            grid_resolution=20,
        )
        plt.savefig('partial_dependence.png', bbox_inches='tight')

    def compute(self, X, feature: str):
        result = partial_dependence(
            self.model,
            X,
            features=[feature],
            grid_resolution=50,
        )
        return {
            'values': result['grid_values'][0],
            'average': result['average'][0],
        }
```

## 7. 模型可解释性 API

### 7.1 解释服务

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

class ExplainRequest(BaseModel):
    model_name: str
    instance: dict
    method: str = "shap"

class ExplainResponse(BaseModel):
    feature_importance: list[dict]
    prediction: float
    explanation: str

@app.post("/explain", response_model=ExplainResponse)
async def explain_prediction(request: ExplainRequest):
    model = model_registry.get(request.model_name)
    if not model:
        raise HTTPException(status_code=404, detail="模型不存在")

    # 转换输入
    instance = preprocessor.transform(request.instance)

    # 预测
    prediction = model.predict_proba([instance])[0]

    # 解释
    if request.method == "shap":
        explainer = SHAPExplainer(model)
        shap_values = explainer.explain(instance.reshape(1, -1))
        feature_importance = [
            {"feature": name, "shap_value": float(value)}
            for name, value in zip(feature_names, shap_values[0])
        ]
    elif request.method == "lime":
        explainer = LIMEExplainer(...)
        exp = explainer.explain_instance(instance, model.predict_proba)
        feature_importance = [
            {"feature": name, "weight": weight}
            for name, weight in exp.as_list()
        ]

    return ExplainResponse(
        feature_importance=feature_importance,
        prediction=float(prediction[1]),
        explanation=f"预测为高风险的概率是 {prediction[1]:.2%}",
    )
```

## 8. 可解释性检查清单

- [ ] 特征重要性
- [ ] 排列重要性
- [ ] SHAP 解释
- [ ] SHAP 交互
- [ ] LIME 解释
- [ ] 反事实解释
- [ ] 部分依赖图
- [ ] 解释 API
- [ ] 可视化
- [ ] 医生友好
- [ ] 合规性
- [ ] 模型监控

---

*可解释性是医疗 AI 的信任基石。让每一个预测都有迹可循，让医生和患者都能理解。*
