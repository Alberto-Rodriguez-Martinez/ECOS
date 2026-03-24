import serial, time

class Scanner():
    def __init__(self,COM,baudrate):
        self.error = True
        self.COM = COM
        self.baudrate = baudrate
        self.ser = serial.Serial()
        self.Init()
        # self.ser.open()
        time.sleep(1)
    
    def Init(self):
        try:
            self.ser.close()
        except:
            pass
        self.ser = serial.Serial()
        #possible timeout values:
        #    1. None: wait forever, block call
        #    2. 0: non-blocking mode, return immediately
        #    3. x, x is bigger than 0, float allowed, timeout block call
        self.ser.port = self.COM
        self.ser.baudrate = self.baudrate
        self.ser.bytesize = serial.EIGHTBITS #number of bits per bytes
        self.ser.parity = serial.PARITY_NONE #set parity check: no parity
        self.stopbits = serial.STOPBITS_ONE #number of stop bits
        # self.ser.timeout = None          #block read
        self.ser.timeout = 0.1            #non-block read
        # self.ser.timeout = 2              #timeout block read
        self.ser.xonxoff = False     #disable software flow control
        self.ser.rtscts = False     #disable hardware (RTS/CTS) flow control
        self.ser.dsrdtr = False       #disable hardware (DSR/DTR) flow control
        self.ser.writeTimeout = 2     #timeout for write

    
    def Close(self):
        self.ser.close()
    
    def Open(self):
        try:
            # self.Init()
            # self.ser.open()
            print "COM %s port opened"%(self.COM)
            time.sleep(2)
        except Exception, e:
            print "Failed to open serial port: " + str(e)
            # self.ShowMessage("error open serial port: " + str(e))
    
        
    def isOpened(self):
        return self.ser.isOpen()
        
    def readable(self):
        return self.ser.readline()
        
    def Write(self,cmd):
        

        # to swich axis the a1234 sequence can be redefined============================
        a1 = 'X'
        a2 = 'Y'
        a3 = 'Z'
        a4 = 'R'
         
        if cmd[2] == 'X': 
            c = cmd[:2] + a1 + cmd[3:]
        elif cmd[2] == 'Y':
            c = cmd[:2] + a2 + cmd[3:]
        elif cmd[2] == 'Z':
            c = cmd[:2] + a3 + cmd[3:]
        elif cmd[2] == 'R':
            c = cmd[:2] + a4 + cmd[3:]
        cmd = c
        #==============================================================================
        # print 'Serial write',cmd        
                
                
        try:
            # self.Init()
            if self.ser.isOpen() == False:
                self.ser.open()
                print "%s> Port opened"%(self.COM)
        except Exception, e:
            # print "error open serial port: " + str(e)
            # self.ShowMessage("error open serial port: " + str(e))
            print "%s> error communicating...: %s"%(self.COM,str(e))
            self.error = True
            self.ser.close()
            # self.ser.open()
            # exit()
        if self.ser.isOpen():
            try:
                self.ser.flushInput() #flush input buffer, discarding all its contents
                self.ser.flushOutput()#flush output buffer, aborting current output
                                      #and discard all that is in buffer
            #write data

                self.ser.write(cmd+'\r')
                #self.main.Output("%s %s> write: %s"%(self.name,self.COM,cmd))
                self.error = False
                time.sleep(0.1)  #give the serial port sometime to receive the data
                # response = self.ser.readline()
                # print response
                response = self.ser.read(10)
                if cmd[:2] == "SM":
                    while response == "":
                    # self.ser.write(cmd+'\r')
                        time.sleep(0.2)
                        response = self.ser.read(10)
                return response
            except Exception, e1:
                # print "error communicating...: " + str(e1)
                self.error = True
                self.ser.close()
                # self.ShowMessage("error communicating...: " + str(e1))
                print "%s> error communicating...: %s"%(self.COM,str(e))
                print "%s> Port closed"%(self.COM)
        else:
            pass
            # print "cannot open serial port "