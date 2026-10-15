"Finite reliability controls and verification."
def expected(case,stage):
    events=['ACQUIRE_A']
    if stage['inject_exception']:events.append('EXCEPTION_'+case['exception'])
    if stage['policy']=='BALANCED_CONTEXT':events.append('RELEASE_A')
    unmatched=sum(x.startswith('ACQUIRE_') for x in events)-sum(x.startswith('RELEASE_') for x in events)
    blocked=unmatched!=0
    if not blocked:events+=['ACQUIRE_B','RELEASE_B']
    exceptions=[x[len('EXCEPTION_'):] for x in events if x.startswith('EXCEPTION_')]
    return dict(first_exception=exceptions[0] if exceptions else None,locked_after_first=blocked,second_entered=not blocked,
        locked_after_second=sum(x.startswith('ACQUIRE_') for x in events)!=sum(x.startswith('RELEASE_') for x in events))
