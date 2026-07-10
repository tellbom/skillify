# Example

Input (pasted by the user):

```csv
region,product,amount
east,widget,100
east,gadget,50
west,widget,80
west,widget,20
```

Request: "pivot this by region, sum amount"

Expected output:

| region | total_amount |
| --- | --- |
| east | 150 |
| west | 100 |
