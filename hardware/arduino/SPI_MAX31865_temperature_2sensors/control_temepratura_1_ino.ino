#include <SPI.h>
#include <math.h>

// ================= Pins =================
static const int CSB1_pin  = 6;
static const int CSB2_pin  = 5;
static const int DRDYB_pin = 7;
static const int RELAY_PIN = 8;

// ================= Relay logic =================
// true  -> relay turns ON with HIGH
// false -> relay turns ON with LOW
static const bool RELAY_ACTIVE_HIGH = true;

// ================= Setpoint & Safety =================
static const double SETPOINT_C        = 36.1;

// Safety: if the "hot spot" sensor exceeds this, heater is forced OFF
static const double SAFETY_CUTOFF_C   = 36.6;
static const double SAFETY_REENABLE_C = 36.3;

// ================= Timing / Relay =================
static const unsigned LOOP_MS       = 200;    // main loop period
static const unsigned WINDOW_MS     = 15000;  // time-proportioning window
static const unsigned MIN_SWITCH_MS = 3000;   // min time between relay changes

// ================= Filtering =================
static const double EMA_ALPHA       = 0.15;   // temperature EMA
static const double EMA_DERIV_ALPHA = 0.25;   // dT/dt EMA

// ================= PI Controller (Duty 0..1) =================
static const double KP = 0.06;     // duty per °C
static const double KI = 0.0015;   // duty per (°C*s)
static const double KD = 0.0;      // derivative penalty

static const double DUTY_MIN = 0.0;
static const double DUTY_MAX = 0.40;

// Anti-windup clamp for integrator
static const double ITERM_MIN = -0.20;
static const double ITERM_MAX = 1.20;

// ================= SPI / RTD =================
static const byte W_CONFIG   = 0x80;
static const byte R_RTD_MSB  = 0x01;
static const byte R_RTD_LSB  = 0x02;
static const uint32_t Clock_Hz = 1000000UL;
static const byte config = 0b11000001;

static const double R_REF1      = 399.5;
static const double R_REF2      = 399.5;
static const double RTD_at_0deg = 100.0;
static const double a           = 0.00390830;
static const double b           = -0.0000005775;

// ================= Variables =================
double temperature1 = NAN;
double temperature2 = NAN;

// Control sensor (T1) and safety sensor (T2)
double tControlRaw  = NAN;
double tSafetyRaw   = NAN;

double tControlFilt = NAN;
double tSafetyFilt  = NAN;

double tPrevControlFilt = NAN;
double dTdtFilt = 0.0;   // filtered derivative (°C/s)

// PI controller states
double iTerm   = 0.0;    // integral term (in duty units)
double dutyCmd = 0.0;    // final duty 0..1

// Windowing & relay state
unsigned long lastLoopMs    = 0;
unsigned long lastSwitchMs  = 0;
unsigned long windowStartMs = 0;
bool relayOn = false;

// Safety latch
bool safetyLatchedOff = false;

// ================= Helpers =================
inline void spiBegin() {
  SPI.beginTransaction(SPISettings(Clock_Hz, MSBFIRST, SPI_MODE3));
}

inline void spiEnd() {
  SPI.endTransaction();
}

static inline double emaUpdate(double prev, double x, double alpha) {
  return isnan(prev) ? x : prev + alpha * (x - prev);
}

static inline bool saneTemp(double t) {
  return !isnan(t) && isfinite(t) && t > -50.0 && t < 150.0;
}

static inline double clamp(double x, double lo, double hi) {
  if (x < lo) return lo;
  if (x > hi) return hi;
  return x;
}

void writeRelayOutput(bool onState) {
  if (RELAY_ACTIVE_HIGH) {
    digitalWrite(RELAY_PIN, onState ? HIGH : LOW);
  } else {
    digitalWrite(RELAY_PIN, onState ? LOW : HIGH);
  }
}

// ================= SPI / RTD functions =================
void writeConfig(int csPin, byte cfg) {
  spiBegin();
  digitalWrite(csPin, LOW);
  SPI.transfer(W_CONFIG);
  SPI.transfer(cfg);
  digitalWrite(csPin, HIGH);
  spiEnd();
}

byte readReg(int csPin, byte addr) {
  spiBegin();
  digitalWrite(csPin, LOW);
  SPI.transfer(addr);
  byte v = SPI.transfer(0xFF);
  digitalWrite(csPin, HIGH);
  spiEnd();
  return v;
}

bool readRTDcode(int csPin, uint16_t &code15, byte &fault) {
  unsigned long t0 = millis();
  while (digitalRead(DRDYB_pin) != LOW) {
    if (millis() - t0 > 100) break;
  }

  byte msb = readReg(csPin, R_RTD_MSB);
  byte lsb = readReg(csPin, R_RTD_LSB);

  fault = (lsb & 0x01);
  code15 = ((uint16_t)msb << 7) | ((lsb >> 1) & 0x7F);

  return (fault == 0);
}

inline double codeToOhms(uint16_t code15, double Rref) {
  return code15 * Rref / 32768.0;
}

inline double ohmsToDegC(double R) {
  const double R0 = RTD_at_0deg;
  double disc = (R0 * R0 * a * a) - 4.0 * R0 * b * (R0 - R);
  if (disc < 0.0) return NAN;
  return (-R0 * a + sqrt(disc)) / (2.0 * R0 * b);
}

double readTemperature(int csPin, double Rref) {
  for (int i = 0; i < 4; i++) {
    uint16_t code;
    byte fault;
    if (readRTDcode(csPin, code, fault) && code != 0) {
      return ohmsToDegC(codeToOhms(code, Rref));
    }
    delay(2);
  }
  return NAN;
}

// ================= Relay helper =================
void applyRelay(bool wantOn, unsigned long now) {
  bool canSwitch = (now - lastSwitchMs) >= MIN_SWITCH_MS;

  if (wantOn != relayOn && canSwitch) {
    relayOn = wantOn;
    lastSwitchMs = now;
  }

  writeRelayOutput(relayOn);
}

// ================= Setup =================
void setup() {
  Serial.begin(115200);

  pinMode(CSB1_pin, OUTPUT);
  digitalWrite(CSB1_pin, HIGH);

  pinMode(CSB2_pin, OUTPUT);
  digitalWrite(CSB2_pin, HIGH);

  pinMode(DRDYB_pin, INPUT_PULLUP);

  pinMode(RELAY_PIN, OUTPUT);
  relayOn = false;
  writeRelayOutput(false);

  SPI.begin();
  delay(10);

  writeConfig(CSB1_pin, config);
  delay(2);
  writeConfig(CSB2_pin, config);
  delay(2);

  // Initial reads
  temperature1 = readTemperature(CSB1_pin, R_REF1);
  temperature2 = readTemperature(CSB2_pin, R_REF2);

  // Default: T1 is control, T2 is safety
  tControlRaw = temperature1;
  tSafetyRaw  = temperature2;

  // Initialize filters
  if (saneTemp(tControlRaw)) tControlFilt = tControlRaw;
  if (saneTemp(tSafetyRaw))  tSafetyFilt  = tSafetyRaw;

  tPrevControlFilt = tControlFilt;
  dTdtFilt = 0.0;

  lastLoopMs    = millis();
  lastSwitchMs  = lastLoopMs;
  windowStartMs = lastLoopMs;
}

// ================= Loop =================
void loop() {
  unsigned long now = millis();
  unsigned long dtMs = now - lastLoopMs;

  if (dtMs < LOOP_MS) return;
  lastLoopMs = now;

  // Read sensors
  temperature1 = readTemperature(CSB1_pin, R_REF1);
  temperature2 = readTemperature(CSB2_pin, R_REF2);

  // Assign roles
  tControlRaw = temperature1;
  tSafetyRaw  = temperature2;

  // If either is invalid -> heater OFF
  if (!saneTemp(tControlRaw) || !saneTemp(tSafetyRaw)) {
    safetyLatchedOff = true;
    dutyCmd = 0.0;
    iTerm = 0.0;
    applyRelay(false, now);

    Serial.print(temperature1, 3);
    Serial.print("\t");
    Serial.println(temperature2, 3);
    return;
  }

  // Filter temperatures
  tControlFilt = emaUpdate(tControlFilt, tControlRaw, EMA_ALPHA);
  tSafetyFilt  = emaUpdate(tSafetyFilt,  tSafetyRaw,  EMA_ALPHA);

  // Derivative estimation on control temperature (°C/s)
  double dtS = (dtMs > 0) ? (dtMs / 1000.0) : 0.2;
  double dTdt = (tControlFilt - tPrevControlFilt) / dtS;
  dTdtFilt = emaUpdate(dTdtFilt, dTdt, EMA_DERIV_ALPHA);
  tPrevControlFilt = tControlFilt;

  // ================= Safety latch =================
  if (tSafetyFilt >= SAFETY_CUTOFF_C) {
    safetyLatchedOff = true;
  } else if (tSafetyFilt <= SAFETY_REENABLE_C) {
    safetyLatchedOff = false;
  }

  if (safetyLatchedOff) {
    dutyCmd = 0.0;
    iTerm = 0.0;
    applyRelay(false, now);
  } else {
    // ================= PI Control (duty 0..1) =================
    double error = SETPOINT_C - tControlFilt;

    // Proportional
    double pTerm = KP * error;

    // Derivative penalty: only penalize positive temperature rise
    double risingRate = (dTdtFilt > 0.0) ? dTdtFilt : 0.0;
    double dPenalty = KD * risingRate;

    // Candidate integrator
    double iNew = iTerm + (KI * error * dtS);

    // Unsaturated duty using candidate integrator
    double dutyUnsat = pTerm + iNew - dPenalty;

    // Anti-windup
    if (!((dutyUnsat > DUTY_MAX && error > 0.0) ||
          (dutyUnsat < DUTY_MIN && error < 0.0))) {
      iTerm = iNew;
    }

    // Clamp integrator
    iTerm = clamp(iTerm, ITERM_MIN, ITERM_MAX);

    // Final duty
    dutyCmd = pTerm + iTerm - dPenalty;
    dutyCmd = clamp(dutyCmd, DUTY_MIN, DUTY_MAX);

    // ================= Time-proportioning window =================
    if (now - windowStartMs >= WINDOW_MS) {
      unsigned long windowsElapsed = (now - windowStartMs) / WINDOW_MS;
      windowStartMs += windowsElapsed * WINDOW_MS;
    }

    unsigned long windowPos = now - windowStartMs;
    unsigned long onTimeMs = (unsigned long)(dutyCmd * (double)WINDOW_MS);

    bool wantOn = (windowPos < onTimeMs);

    // Apply relay with minimum switching protection
    applyRelay(wantOn, now);
  }

  // ================= Telemetry =================
  Serial.print(temperature1, 3);
  Serial.print("\t");
  Serial.println(temperature2, 3);
}