"""Owned async resource-release example; no service or network access."""
async def use_resource(resource, operation):
    await resource.acquire()
    await operation()
    resource.release()
