import array


def _sq_segment_distance(p, p1, p2):
    """Square distance between point *p* and segment *p1*–*p2*."""
    x = p1[0]
    y = p1[1]

    dx = p2[0] - x
    dy = p2[1] - y

    if dx != 0 or dy != 0:
        t = ((p[0] - x) * dx + (p[1] - y) * dy) / (dx * dx + dy * dy)

        if t > 1:
            x = p2[0]
            y = p2[1]
        elif t > 0:
            x += dx * t
            y += dy * t

    dx = p[0] - x
    dy = p[1] - y

    return dx * dx + dy * dy


def _douglas_peucker(points: array.array, tolerance: float) -> array.array:
    length = len(points) // 2
    first = 0
    last = length - 1

    first_stack: list[int] = []
    last_stack: list[int] = []

    new_points = array.array("I")
    markers = [first, last]

    while last:
        max_sqdist = 0
        index = first

        for i in range(first, last):
            point_i = points[i * 2 : i * 2 + 2]
            point_first = points[first * 2 : first * 2 + 2]
            point_last = points[last * 2 : last * 2 + 2]
            sqdist = _sq_segment_distance(point_i, point_first, point_last)

            if sqdist > max_sqdist:
                index = i
                max_sqdist = sqdist

        if max_sqdist > tolerance:
            markers.append(index)

            first_stack.append(first)
            last_stack.append(index)

            first_stack.append(index)
            last_stack.append(last)

        first = first_stack.pop() if first_stack else None
        last = last_stack.pop() if last_stack else None

    markers.sort()
    for i in markers:
        new_points.extend(points[i * 2 : i * 2 + 2])

    # Deduplicate when simplified to a single repeated point
    if (
        len(new_points) == 4
        and new_points[0] == new_points[2]
        and new_points[1] == new_points[3]
    ):
        new_points.pop()
        new_points.pop()
    return new_points


def simplify(points: array.array, tolerance: float = 1.0) -> array.array:
    return _douglas_peucker(points, tolerance * tolerance)


def simplify_polygons(polygons_arr, tolerance: float = 1.0):
    from .containers import EfficientArray

    result = EfficientArray()
    for i in range(len(polygons_arr)):
        polygon = polygons_arr.get_values(i)
        result.add_values(simplify(polygon, tolerance))
    assert len(polygons_arr) == len(result)
    return result
