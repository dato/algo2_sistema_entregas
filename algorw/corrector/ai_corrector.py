import time
import random

VIDA_ACTIVADA = True
FRIDAY = 4
SATURDAY = 5
SUNDAY = 6
LIMIT_HOUR = 23
MINIMUM_HOUR = 7

def movie_generation():
  return random.choice(["Pulp Fiction", "Terminator 2", "Mystic River", "Zoolander"])

FRASES_CORRECTOR = [
  lambda entrega: "El corrector estaba durmiendo..",
  lambda entrega: f"Hola, si estás ahora haciendo una entrega de {entrega}, te recomiendo que mejor veas " + movie_generation(),
  lambda entrega: "La vida social un viernes/sabado a la noche tambien es importante para la salud",
  lambda entrega: "Se derramo cerveza sobre el servidor, esperemos que no afecte las pruebas",
  lambda entrega: "El corrector está de juerga a estas horas. Cualquier resultado de la ejecución de pruebas no puede tomarse seriamente",
  lambda entrega: f"Andá a dormir, mañana tenés todo el día para seguir mandando {entrega}s",
  lambda entrega: "Andá a tomarte unas birras. Yo invito. \n(PD: el corrector automático no cuenta con dinero propio, no tomar seriamente la oferta)",
  lambda entrega: "Hay una alta probabilidad que hayas escrito ese código en estado de ebriedad. Esto puede salir muy bien, o muy mal",
  lambda entrega: "Gracias por hacerme compañía, todos los ayudantes se fueron de joda y me dejaron acá solo corrigiendo pilas y vectores dinámicos",
  lambda entrega: "Sin televisión y sin cerveza, Homero pierde la cabeza"
]

def vida_corrector(entrega):
  """ Si el alumno esta haciendo entregas en horarios estramboticos, responderle con un mensaje 
  que cuide de su salud. 
  """
  if not VIDA_ACTIVADA:
  	return ""

  localtime = time.localtime()
  if (localtime.tm_wday == FRIDAY and localtime.tm_hour >= LIMIT_HOUR) or \
    (localtime.tm_wday == SATURDAY and localtime.tm_hour <= MINIMUM_HOUR) or \
    (localtime.tm_wday == SATURDAY and localtime.tm_hour >= LIMIT_HOUR) or \
    (localtime.tm_wday == SUNDAY and localtime.tm_hour <= MINIMUM_HOUR):
    return random.choice(FRASES_CORRECTOR)(entrega) + "\n\n"
  elif localtime.tm_hour >= LIMIT_HOUR or localtime.tm_hour <= MINIMUM_HOUR:
    return "Recordá que dormir es muy importante para la salud\n\n"
  else:
    return ""
