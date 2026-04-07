from __future__ import annotations

from .lib.AnnoClasses import Heatmap, Points, Polygons

# JSON values as returned by :meth:`requests.Response.json` / :func:`json.loads`.
type JSONValue = str | int | float | bool | None | list[JSONValue] | dict[str, JSONValue]
type JSONObject = dict[str, JSONValue]

# Typed names for ``answer`` JSON decoded into :attr:`SlideScoreResult.annotations` /
# :attr:`SlideScoreResult.points` (same structure, different semantics).
type SlideScoreAnnotationJson = JSONObject
type SlideScorePointCoordJson = JSONObject

# Query/form parameter values (omitted when ``None``).
type APIParamValue = str | int | float | bool | None

# Optional identifiers passed through to SlideScore anno conversion endpoints.
type Anno2OptionalId = int | str | None

type Anno2ConvertInput = Points | Polygons | Heatmap | list[JSONObject]
