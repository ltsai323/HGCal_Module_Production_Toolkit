## algorithms for getIV.py

For each 25V, testing current.

* **setting** NPLC = 10 for better current precision
* let keithley continuously reading current (only read current)
* after 1.5 second, record 4 data point. ( around 1 second)
* remove 1 outliers and take average. (remove 1 point once this point leads to larger std error)
* finally, measure current voltage using NPLC=1
