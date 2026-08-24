<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class GiftVoucher extends Model
{
    protected $connection = 'exchange';
    protected $table = 'gift_vouchers';
    public $timestamps = false;
    protected $guarded = ['*'];
}
