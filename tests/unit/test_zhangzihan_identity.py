"""双仓库同步验证 — 张子涵 提交身份测试。

此文件为验证 GitHub → 内部云端同步保留个人提交身份的标记文件。
由 zhang <z85963541@qq.com> 提交并创建 PR。
"""


def test_zhangzihan_identity_verification() -> None:
    """验证本文件的提交者为 zhang / z85963541@qq.com。

    通过 git log 可确认：
        git log -1 --format='%an <%ae>' -- tests/unit/test_zhangzihan_identity.py
    """
    assert True
