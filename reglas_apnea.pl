% reglas_apnea.pl

% ---------------------------------------------------------
% 1. DEFINICIÓN DE ESTADOS CLÍNICOS
% ---------------------------------------------------------
% Evalúa el nivel de riesgo (0 - 100) y asigna una etiqueta de estado.
estado(verde, Nivel) :- Nivel < 25.
estado(amarillo, Nivel) :- Nivel >= 25, Nivel < 50.
estado(rojo, Nivel) :- Nivel >= 50, Nivel < 75.
estado(emergencia, Nivel) :- Nivel >= 75.

% ---------------------------------------------------------
% 2. ACCIONES DE HARDWARE Y CONSOLA
% ---------------------------------------------------------
% Formato de la regla: 
% accion(Color, Nivel_Calculado, Mensaje_Consola, Pin_Led_R, Pin_Led_G, Pin_Led_B, Pin_Buzzer).

accion(verde, Nivel, 'Paciente estable. No se detectan anomalias respiratorias.', 0, 1, 0, 0) :- 
    estado(verde, Nivel).

accion(amarillo, Nivel, 'PRECAUCION: Apnea moderada. Alteracion en SpO2 y HR.', 1, 1, 0, 0) :- 
    estado(amarillo, Nivel).

accion(rojo, Nivel, 'PELIGRO: Apnea severa. Patrones anomalos prolongados.', 1, 0, 0, 0) :- 
    estado(rojo, Nivel).

accion(emergencia, Nivel, 'CRITICO: Falla respiratoria aguda. URGENTE AL HOSPITAL.', 1, 0, 0, 1) :- 
    estado(emergencia, Nivel).