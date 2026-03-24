import numpy as np
from SeDaq import *
import matplotlib.pylab as plt
import winsound

''' Get Ascans '''
#Get Ascans ->
def GatAscan_Ch2(Smin, Smax, AvgSamplesNumber = 10, Quantiz_Levels = 1024):
    '''Get Ascan fomr channel 2 only, and extract data between Smin and Smax
    and normalizes according to quantization levels, and averages according to 
    number of samples acquired at each point
    '''
    SeDaq = SeDaqDLL()
    Ascan_Ch2 = np.zeros(Smax-Smin)
    Flag = AvgSamplesNumber
    while Flag > 0:
        SeDaq.GetAScan() #get Ascan        
        Aux_Ch2 = np.array(list(map(float,SeDaq.DataADC2[Smin:Smax]))) #get Ascan WP
        Aux_Ch2 = (Aux_Ch2 - Quantiz_Levels/2)/Quantiz_Levels # Normalize 
        Aux_Ch2 = Aux_Ch2 - np.mean(Aux_Ch2) # remove mean        
        if not(np.all(Aux_Ch2==0.0)):	            
            Ascan_Ch2 = Ascan_Ch2 + Aux_Ch2		
            Flag -= 1            		
    Ascan_Ch2 = Ascan_Ch2 / AvgSamplesNumber #calculate averaged Ascan
    Ascan_Ch2 = Ascan_Ch2 - np.mean(Ascan_Ch2) #substract mean value
    return Ascan_Ch2

def Plot_Ascan_tf(Ascan, Units_t = 1e6, Units_F = 1e6, Fs=100e6, Fmin = 0,Fmax = 100e6, FigNum=1, FigTitle='Original Ascan'):
    '''Plots Ascan in time and frequency, between Fmin and Fmax
    Units_t is constant to normalize time axis
    Units_F is constant to normalize frequency axis
    Fs sampling frequency
    Fmin lower limit, considering Units_F
    Fmax upper limit, considering Units_F
    '''
    Time_Axis = np.arange(0, Ascan.size)/Fs*Units_t
    fig, axs = plt.subplots(2, 1, num=FigNum, clear=True)
    axs[0].plot(Time_Axis, Ascan)
#    axs[0].set_title(FigTitle)
    axs[0].set_xlabel('time (us)')
    axs[0].set_ylabel('Ascan')

    # calculate fft
    MyFFT = np.fft.fft(Ascan)
    Freq_Axis = np.arange(0, MyFFT.size)*Fs/MyFFT.size/Units_F
    # freq subplot
    axs[1].plot(Freq_Axis, np.abs(MyFFT))
    axs[1].set_xlabel('frequency (MHz)')
#    axs[1].set_title('subplot 2')
    axs[1].set_ylabel('FFT')
    axs[1].set_xlim(Fmin,Fmax)    
    fig.suptitle(FigTitle)
    plt.show()
	
#Tukey WIN construction
def tukeywin(window_length, alpha):
    '''The Tukey window, also known as the tapered cosine window, can be regarded as a cosine lobe of width \alpha * N / 2
    that is convolved with a rectangle window of width (1 - \alpha / 2). At \alpha = 1 it becomes rectangular, and
    at \alpha = 0 it becomes a Hann window.
 
    We use the same reference as MATLAB to provide the same results in case users compare a MATLAB output to this function
    output
 
    Reference
    ---------
    http://www.mathworks.com/access/helpdesk/help/toolbox/signal/tukeywin.html
 
    '''
    # Special cases
    if alpha <= 0:
        return np.ones(window_length) #rectangular window
    elif alpha >= 1:
        return np.hanning(window_length)
 
    # Normal case
    x = np.linspace(0, 1, window_length)
    w = np.ones(x.shape)
 
    # first condition 0 <= x < alpha/2
    first_condition = x<alpha/2
    w[first_condition] = 0.5 * (1 + np.cos(2*np.pi/alpha * (x[first_condition] - alpha/2) ))
 
    # second condition already taken care of
 
    # third condition 1 - alpha / 2 <= x <= 1
    third_condition = x>=(1 - alpha/2)
    w[third_condition] = 0.5 * (1 + np.cos(2*np.pi/alpha * (x[third_condition] - 1 + alpha/2))) 
 
    return w

''' END of tukey window definition  '''


''' Gating procedure '''
#Get reflection signal (Gate out) ->
def GateOut(FilteredSignal):
    from scipy import signal
#    global tukeywin
    
    N=len(FilteredSignal)    
    NoOfDipsToStart=1 #1
    NoOfDipsToEnd=1 #1
    Add0Start=150 #10
    Add0End=250 #150 
    TukeyDecaySpeed=0.3 #30% decay.
    ThresholdLevelProc=0.5 #0.2
    SigNenv=abs(signal.hilbert(FilteredSignal))
    SigNenv=SigNenv/max(SigNenv)
    EnvMaxPos=np.argmax(SigNenv)
    positionsAboveTh=np.where(SigNenv[0:EnvMaxPos]>ThresholdLevelProc);
    #Plot(SigNenv[0:EnvMaxPos])
    xx,dipsNr=np.unique(np.diff(positionsAboveTh),return_index=True)
    if (len(dipsNr)<2):
        nr1Sig=positionsAboveTh[0][0]-Add0Start
    else:
        nr1Sig=positionsAboveTh[0][dipsNr[len(dipsNr)-NoOfDipsToStart]]-Add0Start
    #print len(dipsNr)
	#print positionsAboveTh[0][0]
	#print nr1Sig
    if (nr1Sig<0):
        nr1Sig=0
    #print nr1Sig
    positionsAboveTh=np.where(SigNenv[EnvMaxPos:N]>ThresholdLevelProc)
	#Plot(SigNenv[EnvMaxPos:N])
    xx,dipsNr=np.unique(np.diff(positionsAboveTh),return_index=True)
    if (len(dipsNr)<2):
        nr2Sig=positionsAboveTh[0][-1]+Add0End+EnvMaxPos
    else:
        nr2Sig=positionsAboveTh[0][dipsNr[NoOfDipsToEnd]]+Add0End+EnvMaxPos
	#print nr2Sig
	#Plot(SigNenv)
	#Plot(FilteredSignal)
    winLen=int(round((nr2Sig-nr1Sig+1)/(1-TukeyDecaySpeed),0))    
    nr1SigNew=int(round(nr1Sig-winLen*TukeyDecaySpeed/2))
    if nr1SigNew<0:
        nr1SigNew=0
    MyWindow=np.zeros(N)
#    print(N-winLen)
#    print(winLen)
#    print(nr1SigNew)
#    print(len(MyWindow[nr1SigNew:nr1SigNew+winLen]))
    MyWindow[nr1SigNew:nr1SigNew+winLen]=tukeywin(winLen,TukeyDecaySpeed)
#    
#	#Plot1(MyWindow)
    SigGated=MyWindow*FilteredSignal
#	#Plot2(SigGated)
    return SigGated
''' Gating procedure END '''

''' HP Filter '''
#Signal filtering by HP filter
def FilterMySignalHP(ReceivedSignal, CutOffFreq, ADC_CLKfreqMHz):
	from scipy import signal
	
	Wn=CutOffFreq/ADC_CLKfreqMHz # 1MHz
	b, a = signal.butter(4, Wn, 'high')
	zi = signal.lfilter_zi(b, a)
	FilteredSignal, _ = signal.lfilter(b, a, ReceivedSignal, zi=zi*ReceivedSignal[0])
	return FilteredSignal


def makeBeep(frequency = 2500, duration = 1000):
    #frequency = 2500  # Set Frequency To 2500 Hertz
    #duration = 1000  # Set Duration To 1000 ms == 1 second
    winsound.Beep(frequency, duration)