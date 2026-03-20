# HOLA MANGOS -- HOLA KIWIS

import random as rd

print("------MANGOS -vs- KIWIS------\n")

while True:
    try:
#----------HISTORIA----------#
        print("""En un tiempo indeterminado de un futuro muy lejano, los mangos dominaron 
la galaxia, pero, una civilizacion antigua dominada por los kiwis, se alzo contra ellos, y 
se desato una guerra, los kiwis deseaban poder, como todos en la galaxia, pero ellos tenian 
determinacion, entrenaron un ejercito, los platanos se unieron a ellos, el general manzana estaba al mando 
los mangos, ayudados por las piñas y el general durazno, se ponen a la defensiva, hostiles, esperan el ataque...\n""")

        print("""\n¿Que haran los mangos? (1.atacar, 2.defender, 3.negociar)\n""")
        accion = input("Accion: ").lower()

        #----------ACCIONES----------#

        #----ACCION 1: ATACAR----#
        if accion == "atacar" or accion == "1":
            print("""\nLos mangos lanzan un ataque, pero los kiwis no estaban preparados, 
los platanos traen refuerzos, las piñas defienden a los mangos, una masacre total, rebanadas 
de kiwis vuelan por los aires, jugo de mango se derrama por las calles pero estos se mantienen
firmes, una masacre total, esta vez los mangos ganan jugo de kiwi y lo beben en copas de oro en 
modo de celebración...\n""")
            

        #----ACCION 2: DEFENDER----#    
        elif accion == "defender" or accion == "2":
            print("""\nLos kiwis lanzan un ataque sorpresa, pero los mangos estaban preparados, 
las piñas traen refuerzos, defienden a los mangos, una masacre total, rebanadas 
de kiwis vuelan por los aires, jugo de mango se derrama por las calles, una masacre total, los mangos 
se han defendido con exito esta vez pero los kiwis se mantiene firmes...\n""")


        #----ACCION 3: NEGOCIAR----#    
        elif accion == "negociar" or accion == "3":
            print("""\nLos mangos intentan negociar con los kiwis, estos  proponen un trato...
Dividir el territorio en dos partes iguales y mantener un tratado de paz donde cada uno gobierna sus tierras,
o terminar la guerra, un duelo a muerte\n""")
            
        #----SUB-OPCION: DUELO O TRATO----#
            subaccion = input("¿Que opcion eliges? (1.Duelo 2.Trato): ").lower().strip()
            if subaccion in ["duelo", "1", "d"]:
                ganador = rd.choice(["mangos", "kiwis"])
                
                if ganador == "mangos":
                    print("""\nLos mangos y los kiwis se enfrentan en un duelo a muerte, 
el general Manzana y el general Durazno lideran los ataques, una batalla épica se desata, ambos generales 
luchan con valentía, jugo de kiwi y jugo de mango por doquier, una masacre grotesca y llena de desgracia
una batalla historica, un duelo inolvidrable, esta vez los Mangos salen victoriosos.
\nLos kiwis han sido exterminados...\n""")
                    
                else:
                    print("""\nLos mangos y los kiwis se enfrentan en un duelo a muerte, 
el general Durazno y el general Manzana lideran los ataques, una batalla épica se desata, ambos generales 
luchan con valentía, jugo de mango y jugo de kiwi por doquier, una masacre grotesca y llena de desgracia
una batalla historica, un duelo inolvidrable, esta vez los Kiwis salen victoriosos.
\nLos Mangos han sido exterminados...\n""")
                    
            elif subaccion in ["trato", "2", "t"]:
                print("""\nLos mangos y los kiwis llegan a un acuerdo, dividen el territorio en dos partes iguales
y mantienen un tratado de paz, cada uno gobierna sus tierras, una era de prosperidad y armonia se desata en la galaxia.""")
            else:
                print("\nOpcion no valida en negociacion. Intenta de nuevo.\n")
            
        #----ACCION NO VALIDA----#
        else:
            print("\nAccion no valida, intenta de nuevo.\n")

        #----OPCION DE VOLVER A JUGAR----#
        opcion = input("¿Deseas intentar de nuevo? (si/no): ").lower()
        if opcion != "si" and opcion != "s":
            print("\nGracias por jugar, adios!\n")
            break

    except Exception as e:
        print(f"\nOcurrio un error: {e}\n")
        print("Intenta de nuevo.\n")
