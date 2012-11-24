#include "Python.h"

// compute the checksum for the cabinet's CFDATA datablock
unsigned long int checksum(unsigned char *in, unsigned short int ncbytes, unsigned long int seed)
{
	int no_ulongs;
	unsigned long int csum=0;
	unsigned char *stroom;
	unsigned long int temp;

	no_ulongs = ncbytes / 4;
	csum = seed;
	stroom = in;

	while(no_ulongs-->0)
	{
		temp = ((unsigned long int) (*stroom++));
		temp |= (((unsigned long int) (*stroom++)) << 8);
		temp |= (((unsigned long int) (*stroom++)) << 16);
		temp |= (((unsigned long int) (*stroom++)) << 24);

		csum ^= temp;
	}

	temp = 0;
	switch(ncbytes%4)
	{
		case 3: temp |= (((unsigned long int) (*stroom++)) << 16);
		case 2: temp |= (((unsigned long int) (*stroom++)) << 8);
		case 1: temp |= ((unsigned long int) (*stroom++));
		default: break;
	}
	
	csum ^= temp;

	return csum;	
}


static PyObject *
p_checksum(self, args)
        PyObject *self, *args;
{
 PyObject *o;
 char *s;
 unsigned int size, seed = 0;

 if (!PyArg_ParseTuple(args,"s#|I",&s,&size,&seed)) return 0;

 return Py_BuildValue("I", checksum(s,size,seed));
}


static PyMethodDef checksum_methods[] =
{
 {"checksum", p_checksum, METH_VARARGS, "checksum(s, seed)"},
 {NULL, NULL, 0, NULL}
};

__declspec(dllexport)
void
init_checksum()
{
 Py_InitModule("_checksum", checksum_methods);
}
