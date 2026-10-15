"Finite reliability controls and verification."
def expected(case,stage):
    held=False;first_error=None
    held=True
    if stage['inject_exception']:first_error=case['exception']
    if stage['policy']=='BALANCED_CONTEXT':held=False
    blocked=held
    if not blocked:
        held=True
        held=False
    return dict(first_exception=first_error,locked_after_first=blocked,second_entered=not blocked,locked_after_second=held)
