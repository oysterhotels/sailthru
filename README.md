sailthru
========

Python interface to the [Sailthru email API](http://docs.sailthru.com/api), as used by [Oyster.com](http://www.oyster.com/).

Simple example:

```python
>>> import sailthru
>>> sailthru.send_mail('Welcome', 'bob@example.com', name='Bobby')
>>> sailthru.send_blast('Weekly Update', 'Newsletter', 'The CEO', 'ceo@example.com',
                        'Your weekly update', '<p>This is a weekly update!</p>')
```

See the docstring comments in the code and the [Sailthru API docs](http://docs.sailthru.com/api) for more details.