问题在循环体。`items` 是列表，迭代出来的是元素本身，不是键；你却又用元素去索引字典，所以报 KeyError。

照这个改：

```python
def count(items):
    total = 0
    for value in items:
        total += value
    return total
```

如果 items 原本是「名称到数值」的字典，那就别遍历它，直接遍历值：

```python
def count(items):
    return sum(items.values())
```

先看清楚传进来的是列表还是字典，这两种写法看着像，语义完全不同。改完把测试跑一遍确认行为对不对吧。

照做就行，别在循环里再套一层取值。
