"""
Enhanced Kalman filter implementation for glucose trend prediction
Based on the updated Jupyter notebook implementation
"""

import numpy as np
import datetime

# Define glucose thresholds for diabetes events
SEVERE_HYPO_THRESHOLD = 54  # mg/dL
MILD_HYPO_THRESHOLD = 69    # mg/dL
HYPER_THRESHOLD = 181       # mg/dL
SAFE_LOWER = 70             # mg/dL
SAFE_UPPER = 180            # mg/dL

# Optimized parameters from grid search
OPTIMAL_Q = 1.0
OPTIMAL_R = 0.0517947467923121
OPTIMAL_P0 = 5.0
OPTIMAL_MAX_PREDICT_STEPS = 1   # Always predicting the next sample (5 min ahead)
OPTIMAL_MIN_DURATION = 1        # Minimum consecutive points for a state change

def preprocess_time_strings(time_strs):
    """
    Preprocess a list/array of time strings.
    If a time string starts with "00:" (as in "00:00:00 PM"), replace it with "12:" so it
    can be correctly parsed in 12-hour format.
    """
    new_times = []
    for ts in time_strs:
        if isinstance(ts, str):
            ts = ts.strip()
            if ts.startswith("00:"):
                ts = "12:" + ts[3:]
        new_times.append(ts)
    return new_times

def kalman_filter(z, Q=OPTIMAL_Q, R=OPTIMAL_R, x0=None, P0=OPTIMAL_P0):
    """
    Basic 1D Kalman Filter.

    z  : array of measurements
    Q, R: process and measurement noise variances
    x0 : initial state estimate
    P0 : initial covariance estimate

    Returns:
      x_est : filtered estimates
      P     : error covariances
    """
    if x0 is None and len(z) > 0:
        x0 = z[0]

    if len(z) == 0:
        return np.array([]), np.array([])

    n = len(z)
    x_est = np.zeros(n)
    P = np.zeros(n)

    # Initialize
    x_est[0] = x0
    P[0] = P0

    for k in range(1, n):
        # Prediction step
        x_pred = x_est[k-1]
        P_pred = P[k-1] + Q

        # Update step
        K = P_pred / (P_pred + R)
        x_est[k] = x_pred + K * (z[k] - x_pred)
        P[k] = (1 - K) * P_pred

    return x_est, P

def multi_horizon_prediction(z, predict_steps=OPTIMAL_MAX_PREDICT_STEPS, interval_minutes=5,
                             Q=OPTIMAL_Q, R=OPTIMAL_R, P0=OPTIMAL_P0):
    """
    Enhanced Kalman filter that tracks position (glucose level) and velocity.
    It produces one-step-ahead predictions (i.e. 5 minutes ahead).

    Parameters:
    z : array of glucose measurements
    predict_steps : how many steps to predict into the future (default 1 - 5 minutes)
    interval_minutes : time between glucose readings in minutes (default 5)
    Q : process noise variance
    R : measurement noise variance
    P0 : initial covariance estimate

    Returns:
    x_est : filtered estimates for the input data
    future_predictions : predicted values starting from the last measurement
    future_times : timestamps for the future predictions (as regular Python integers)
    """
    if len(z) == 0:
        return np.array([]), np.array([]), np.array([])

    if len(z) < 2:
        return np.array([z[0]]), np.array([]), np.array([])

    x0 = z[0]  # Use first measurement

    # State vector: [position, velocity]
    x_state = np.array([x0, 0])

    # State transition matrix (with velocity)
    A = np.array([[1, interval_minutes], [0, 1]])

    # Process covariance
    P_state = np.array([[P0, 0], [0, Q]])

    # Measurement matrix (only position)
    H = np.array([1, 0])

    # Set up array for filtered values
    n = len(z)
    x_est = np.zeros(n)
    x_est[0] = x0

    # Apply Kalman filter for each point
    for k in range(1, n):
        # Prediction
        x_state = A @ x_state
        P_state = A @ P_state @ A.T + np.array([[Q, 0], [0, Q]])

        # Update
        y = z[k] - H @ x_state
        S = H @ P_state @ H.T + R
        K_gain = P_state @ H.T / S
        x_state = x_state + K_gain * y
        P_state = (np.eye(2) - np.outer(K_gain, H)) @ P_state

        # Store the filtered value
        x_est[k] = x_state[0]

    # Now generate future predictions
    future_predictions = np.zeros(predict_steps)
    future_state = x_state.copy()

    # Generate prediction steps ahead
    for i in range(predict_steps):
        # Predict one step ahead
        future_state = A @ future_state

        # Store the predicted glucose level (position component)
        future_predictions[i] = future_state[0]

    # Convert to minutes for future times
    future_times = [(i+1) * interval_minutes for i in range(predict_steps)]

    return x_est, future_predictions, future_times

def get_glucose_state(glucose):
    """
    Determine the state based on glucose value
    0: safe, 1: mild hypoglycemia, 2: severe hypoglycemia, 3: hyperglycemia
    """
    if glucose <= SEVERE_HYPO_THRESHOLD:
        return 2  # Severe hypoglycemia
    elif glucose <= MILD_HYPO_THRESHOLD:
        return 1  # Mild hypoglycemia
    elif glucose >= HYPER_THRESHOLD:
        return 3  # Hyperglycemia
    else:
        return 0  # Safe range