"""Filter a tree without changing its original keys or insertion positions."""

def filter_tree(editor, query='', role='All tags'):
    query=query.strip().casefold()
    matches=set()
    for key in editor.order:
        node=editor.nodes[key]
        if role!='All tags' and (not node.structure or str(node.obj.S).lstrip('/')!=role):
            continue
        fields=[node.label]
        if node.structure:
            fields.extend(str(node.obj.get(prop,'')) for prop in ('/T','/Alt','/ActualText','/Lang','/E','/ID'))
        if query and query not in ' '.join(fields).casefold():
            continue
        matches.add(key)
    # Show matching containers' contents, along with the path to every match.
    descendants=set()
    for key in editor.order:
        if key in matches or editor.parents[key] in descendants:
            descendants.add(key)
    visible=descendants|{'root'}
    for key in matches:
        parent=editor.parents[key]
        while parent not in visible:
            visible.add(parent)
            parent=editor.parents[parent]
    return matches,visible
