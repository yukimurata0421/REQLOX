# Owned path context example

The file is removed when you leave the `with` context.

```python
from pkg import Resource
with Resource() as path:
    path.write_text('data')
```

This is an included owned control. Its normal-exit statement defines the finite
release requirement; it makes no cleanup-error retry guarantee.
