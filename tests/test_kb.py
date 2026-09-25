def test_kb_requires_permission(client, auth):
    racer = auth(client, "racer", "racer1234")
    resp = client.get("/api/kb/documents", headers={"Authorization": f"Bearer {racer}"})
    assert resp.status_code == 403


def test_kb_list(client, auth):
    demo = auth(client, "demo", "demo1234")
    resp = client.get("/api/kb/documents", headers={"Authorization": f"Bearer {demo}"})
    assert resp.status_code == 200
    names = [d["name"] for d in resp.json()["documents"]]
    assert any(n.endswith(".md") for n in names)


def test_kb_upload_and_delete(client, auth):
    demo = auth(client, "demo", "demo1234")
    headers = {"Authorization": f"Bearer {demo}"}
    content = "# 测试文档\n\n## 测试章节\n\n这是一段用于验证上传索引流程的测试内容。".encode("utf-8")
    upload = client.post(
        "/api/kb/documents", headers=headers, files={"file": ("test_doc.md", content, "text/markdown")}
    )
    assert upload.status_code == 200
    name = upload.json()["name"]

    import time
    time.sleep(0.5)

    idx = client.post(f"/api/kb/documents/{name}/index", headers=headers)
    assert idx.status_code == 200

    delete = client.delete(f"/api/kb/documents/{name}", headers=headers)
    assert delete.status_code == 200