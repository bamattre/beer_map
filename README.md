# beer_map
Test project using Claude Code to create an interactive map based on a previous project

## Interactive version (Python / Altair)

`beer_map.py` rebuilds the map as an interactive web page:

```bash
pip install altair pandas
python beer_map.py
```

It writes `docs/index.html`, a single self-contained page. Hover a state for details; click states to filter the bar chart. To publish it, enable GitHub Pages from the `/docs` folder.
