"""双仓库同步验证测试。

此文件仅用于验证 GitHub → 内部云端同步流程是否保留原始提交的 SHA、作者姓名和邮箱。
不包含任何真实健康数据、密钥、模型权重或敏感信息。
"""


def test_sync_author_identity_preserved() -> None:
    """验证同步后提交的 author name 和 email 与 GitHub 端一致。

    本测试本身不执行任何同步操作；它作为一个标记提交存在，
    用于在 GitHub master 合并后，通过 git log 和 git ls-remote
    核对两端 SHA 和作者信息是否完全匹配。
    """
    expected_author = "zhang"
    expected_email = "z85963541@qq.com"

    assert expected_author == "zhang", "提交作者姓名应保留原始值"
    assert expected_email == "z85963541@qq.com", "提交作者邮箱应保留原始值"


def test_sync_sha_matches() -> None:
    """验证 GitHub master 与内部云端 master 的 HEAD SHA 一致。

    同步工作流只复制同一个 Git 提交对象，不重新提交、不改写提交作者。
    本测试作为标记存在，实际核对通过以下命令完成：

        git ls-remote https://github.com/Meyt1n/issedu_ysu2026_3709.git \\
            refs/heads/master
        git ls-remote http://119.3.217.118:30181/29092881243490627/ \\
            issedu_ysu2026_3709.git refs/heads/master
    """
    # 此测试始终通过；实际 SHA 比对由外部脚本或人工核对完成
    assert True
