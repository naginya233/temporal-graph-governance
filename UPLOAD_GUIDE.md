# Upload Guide (GitHub)

## 1) Initialize repository

```bash
cd github_upload_package
git init
git add .
git commit -m "feat: integrate traffic governance pipeline and review console"
```

## 2) Create remote repository on GitHub

Create an empty repo, then run:

```bash
git branch -M main
git remote add origin <YOUR_GITHUB_REPO_URL>
git push -u origin main
```

## 3) Verify after push

- `README.md` renders correctly.
- `traffic_agent_system/` and `DairV2X_SceneGraph_Validator/` are present.
- Runtime outputs/config files are not tracked.
