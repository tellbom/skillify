# Example

Given `sample.txt`:

```
the quick brown fox jumps over the lazy dog
the dog barks at the fox
```

Running:

```
python scripts/word_frequency.py sample.txt --top 3
```

Prints:

```
word      count
------  -------
the           4
fox           2
dog           2
```
