## Using Keras and Deep Deterministic Policy Gradient to play TORCS

300 lines of python code to demonstrate DDPG with Keras

Please read the following blog for details

https://yanpanlau.github.io/2016/10/11/Torcs-Keras.html

![](fast.gif)

# Installation Dependencies:

* Python 2.7
* Keras 1.1.0
* Tensorflow r0.10
* [gym_torcs](https://github.com/ugo-nama-kun/gym_torcs)

# How to Run?

```
git clone https://github.com/yanpanlau/DDPG-Keras-Torcs.git
cd DDPG-Keras-Torcs
cp *.* ~/gym_torcs
cd ~/gym_torcs
python ddpg.py 
```

(Change the flag **train_indicator**=1 in ddpg.py if you want to train the network)
