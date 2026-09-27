# Streamlit 1.45+ navigation and cross-platform filenames

## Implemented status

- All page filenames are plain ASCII; emojis are declared only as `st.Page(icon=...)` values.
- `predictions.py` calls `st.set_page_config()` exactly once.
- `predictions.py` uses explicit `st.navigation()` / `st.Page()` routing.
- No subpage calls `st.set_page_config()`.
- Home shows the logo in its main content. Other pages show it below navigation in the sidebar.
- Redundant sidebar-navigation hint banners are absent.
- Searchable player and tournament selection uses `st.selectbox` where a bounded catalog exists.

This arrangement works consistently on Windows, macOS, Linux containers, and Streamlit Community Cloud because page discovery no longer depends on Unicode filenames or implicit `pages/` scanning.

Verification:

```powershell
rg -n "set_page_config" predictions.py pages
python -m py_compile predictions.py pages/*.py
```
