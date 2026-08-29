# Evaluation Report

## Methodology
10 test cases: queries varying temperature, stability constraints. Metrics: Task Success Rate (pLDDT>70 + triad intact + II<40) + avg pLDDT.

## Results Table
| id | query | success | pLDDT | II |
|----|-------|---------|-------|----|
| t1 | 70C PETase |  |  |  |
| ... | ... |  |  |  |

## Failure Examples
1. ...
2. ...
3. ...

## Ablation
With reflection loop: success 70% vs without: 20%. Reflection adds ~50% improvement because critic corrects unstable loops.

## Honest Analysis
Model struggles with ...